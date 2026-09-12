# Recommendation policy v1

Comparisons now include `recommendation_result` in both PDF and demo mode. This is
an additive field; raw monthly bills and cost ordering remain available. Older
saved comparisons load with `recommendation_result: null` and are not recalculated.

## Using the interface

Enter ZIP and 12 monthly usage values. Under **Recommendation preferences and
current plan**, optionally declare usage provenance and maximum contract length.
Compare to see the primary cost winner, a minimax-regret alternative, top three,
confidence reasons, scenario table, bill-credit probes and evidence.

To estimate savings, compare once, choose the current plan from the populated
catalog list, optionally enter switching costs, and compare again. The baseline
must be a calculable plan for the selected ZIP and source. If your current plan
is absent, leave it blank; arbitrary bill uploads/current tariffs are not yet
supported. A blank switching cost means unknown; enter zero only when appropriate.

Changing ZIP or data source clears the baseline. All input changes invalidate
results. Saved results restore their recommendation options and original analysis.

## API

`POST /api/comparisons` accepts optional `recommendation_options`:

```json
{
  "zip_code": "75201",
  "data_source": "demo",
  "monthly_kwh": [1000,1000,1000,1000,1000,1000,1000,1000,1000,1000,1000,1000],
  "recommendation_options": {
    "usage_provenance": "bills",
    "max_contract_months": 24,
    "baseline_plan_id": "demo-oncor-simple",
    "switching_cost": "60.00"
  }
}
```

All options are optional. Provenance is `unknown`, `estimated`, `bills` or `meter`;
contract ceiling is an integer from 12 to 120 months. Switching cost is a
nonnegative decimal with at most two decimal places. Invalid/currently unqualified
baseline IDs return 422. Existing invalid-ZIP/no-calculable-catalog errors remain
422. If the optional contract filter leaves no candidates, comparison still
returns its raw costs, but the recommendation has `status: no_eligible_plans`,
`best_overall: null` and no top-three entries.

The result contains:

| Field | Meaning |
| --- | --- |
| best_overall | Detailed lowest supplied-usage-cost plan, or null |
| top_3 | Up to three detailed candidates in cost order |
| category_winners | Plan IDs for lowest_estimated_cost and lowest_scenario_regret |
| plan_analyses | Detailed scenario, regret and credit analysis for all candidates |
| baseline | Selected tariff at the same usage; null without a baseline |
| expected_savings | Gross/net estimated savings and cumulative payback; null without baseline/winner |
| confidence / confidence_components / confidence_reasons | Rule-based assessments, not probabilities |
| key_tradeoffs | Additional supplied-usage cost of the minimax-regret option |
| break_even_conditions | Sampled cost-preference brackets and switching recovery |
| warnings / assumptions | Missing evidence and calculation limitations |
| evidence_refs | PDF quotes/pages/revisions, delivery sources and calculation IDs |
| scenarios / policy_version / comparison_horizon / options | Reproducibility and saved input context |

Decimal values are serialized as strings. Recommendation source IDs resolve
within its evidence_refs; calculation IDs identify the accompanying saved scenario
outputs. PDF references preserve component/identity evidence and revision IDs.

## Cost, scenario regret and credits

Policy `cost-first-scenario-regret-v1` selects the lowest cost at supplied usage.
It does not silently substitute minimax regret or net switching savings as the
ranking policy. Equal costs are ordered by plan ID; scenario ranks share ranks for
equal costs. A single eligible plan is explicitly flagged; its zero regret does
not indicate market superiority. An annual gap of $12 or less between the first
two plans is labeled a close alternative, a simple engineering heuristic.

Five common scenarios use multipliers 0.8, 0.9, 1.0, 1.1 and 1.2 on every month,
with usage rounded half-up to four decimal places. Existing Python calculators
calculate each month, preserving conditional-charge and credit rules. No LLM,
Pinecone query or provider fetch runs during recommendation.

Regret = plan annual cost minus the cheapest eligible annual cost in that scenario.
The same preference-filtered candidates compete in every scenario. Maximum regret
is the largest of these five values. Minimax ties break by supplied-usage cost,
then ID. Switching costs are reported separately and are not in scenario regret.
There are no probabilities or forecasts, and these are not bounds over all futures.

Each credit boundary is probed at b-0.0001, b and b+0.0001 kWh, discarding negative
usage. Strict/inclusive lower and upper bounds use the actual calculator. The
result includes bills and credits at each probe, qualifying months, annual credits,
and scenario months with decreased credit amounts. Nearby means within 10% of the
boundary, with a 1-kWh minimum band. Probes are local monthly sensitivity checks;
they are not additional annual regret scenarios.

## Confidence and break-even limits

Confidence is low if usage is unknown/estimated, evidence is synthetic, the primary
plan's issue date is unknown/future/older than 365 days, the winner changes in the
five scenarios, or only one candidate exists. Otherwise it is moderate. High is
not assigned while live availability/address eligibility remain unverified.
User-declared bills/meter provenance is not independently verified. Freshness is
an explicit heuristic, not a claim of legal tariff validity.

A sampled usage bracket records adjacent scenario multipliers where cost preference
between the primary plan and another plan changes (including an observed tie).
It is not an exact continuous break-even point. Multiple crossings and credit
cliffs can lie inside a bracket; crossings between samples can be missed.

Savings compare the selected baseline tariff against the primary plan under the
same 12 months. Gross savings exclude switching costs; net savings subtract the
user-supplied total. Unknown switching cost leaves net savings/payback null. Staying
on the baseline incurs no switching fee. Negative savings are preserved and warned
about. Payback is the first month after which cumulative net savings remain
nonnegative through month 12, not a guarantee beyond the tested horizon.

## Remaining scope

Live eligibility, verified availability, current-plan uploads, renewable attributes,
move-date/termination-rule interpretation, exact continuous break-even solvers,
probability-weighted regret and calibrated confidence need additional data or policy.
The document chat remains a separate evidence-only workflow.

## Verification

`python -m unittest discover -s tests -p test_recommendations.py -v` exercises
independent costs/regret, credit inequalities, seasonal profiles, savings/payback,
contract filters, ties, zero usage, confidence, PDF sources and saved snapshots.
`node --test tests/zip-ui.test.cjs tests/agent-ui.test.cjs` exercises UI options,
rendering, stale responses, saved restoration and existing chat flows.

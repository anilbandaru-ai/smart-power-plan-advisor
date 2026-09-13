"""Deterministic recommendations; caller supplies the existing monthly calculator."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

from backend.projections import project
from backend.recommendation_models import RecommendationResult, RecommendedPlan, ScenarioCost

D = Decimal
SCENARIOS = [("lower_20", D("0.8")), ("lower_10", D("0.9")),
             ("supplied", D("1")), ("higher_10", D("1.1")), ("higher_20", D("1.2"))]
STEP = D("0.0001")


def cash(value):
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Candidate:
    plan_id: str
    name: str
    term_months: int
    calculate: Callable
    boundaries: list
    evidence: list
    issue_date: str | None = None
    pricing_basis: str = "components"


def annual(months):
    return sum((month.total for month in months), D("0.00"))


def credits(candidate, usage, months_by_scenario):
    if candidate.pricing_basis == "efl_average":
        return {"status": "included_in_average", "qualifying_months": [], "annual_credits": None,
            "horizon_credits": None, "threshold_exposure": [], "credit_loss_scenarios": []}
    supplied = months_by_scenario["supplied"]
    exposures = []
    for boundary in sorted(set(candidate.boundaries)):
        probes = []
        for amount in (boundary - STEP, boundary, boundary + STEP):
            if amount >= 0:
                month = candidate.calculate(amount, 1)
                probes.append({"kwh": amount, "bill": month.total, "credit": month.credit})
        exposures.append({"boundary_kwh": boundary, "probe_increment_kwh": STEP,
            "nearby_months": [i + 1 for i, value in enumerate(usage)
                              if abs(value - boundary) <= max(D("1"), boundary * D("0.10"))],
            "probes": probes,
            "bill_difference_across_boundary": probes[-1]["bill"] - probes[0]["bill"]})
    losses = []
    for scenario_id, months in months_by_scenario.items():
        lost = [i + 1 for i, (base, current) in enumerate(zip(supplied, months)) if current.credit < base.credit]
        if lost:
            losses.append({"scenario_id": scenario_id, "months": lost,
                "lost_credit_value": sum((max(D("0"), base.credit - current.credit)
                    for base, current in zip(supplied, months)), D("0.00"))})
    return {"qualifying_months": [m.month for m in supplied if m.credit > 0],
        "annual_credits": sum((m.credit for m in supplied[:12]), D("0.00")),
        "horizon_credits": sum((m.credit for m in supplied), D("0.00")),
        "threshold_exposure": exposures, "credit_loss_scenarios": losses}


def freshness(candidate, today):
    if candidate.issue_date is None:
        return "unknown"
    try:
        from backend.catalog.tdu import parse_date
        issued = parse_date(candidate.issue_date)
        age = (today - issued).days
        return "recent" if 0 <= age <= 365 else "stale_or_future"
    except (ValueError, TypeError):
        return "unknown"


def recommend(request, candidates, data_mode, today=None):
    average_mode = any(c.pricing_basis in ("efl_average", "custom_efl") for c in candidates)
    custom_mode = any(c.pricing_basis == "custom_efl" for c in candidates)
    options = request.recommendation_options
    horizon = options.max_contract_months or 12
    baseline_candidate = None
    if options.baseline_plan_id:
        baseline_candidate = next((c for c in candidates if c.plan_id == options.baseline_plan_id), None)
        if baseline_candidate is None:
            raise ValueError("Current plan must be a calculable plan for this ZIP in the selected data source.")
    excluded = [c for c in candidates if options.max_contract_months and c.term_months > options.max_contract_months]
    candidates = [c for c in candidates if c not in excluded]
    usage = [request.monthly_kwh[i % 12] for i in range(horizon)]
    scenarios = [{"id": key, "multiplier": factor,
        "monthly_kwh": [(value * factor).quantize(STEP, rounding=ROUND_HALF_UP) for value in usage]}
        for key, factor in SCENARIOS]
    renews = any(c.term_months < horizon for c in candidates)
    for scenario in scenarios:
        scenario.update(renewal_escalation_pct=options.renewal_escalation_pct,
                        renewal_credit_policy=options.renewal_credit_policy, renewal_case="base")
    if renews:
        original_scenarios = list(scenarios)
        for label, rate, policy in [("lower", max(D(0), options.renewal_escalation_pct - 5), options.renewal_credit_policy),
                                     ("higher", options.renewal_escalation_pct + 5, "drop")]:
            scenarios.extend({**scenario, "id": scenario["id"] + "_renewal_" + label,
                "renewal_escalation_pct": rate, "renewal_credit_policy": policy, "renewal_case": label}
                for scenario in original_scenarios)
    assumptions = ["Primary recommendation minimizes cost at supplied usage; ties break by plan ID.",
        "Scenario regret compares the same eligible plans in shared usage and renewal scenarios, without probabilities.",
        "Maximum scenario regret excludes untested usage patterns, renewal prices and switching costs.",
        "Credit probes are local boundary checks, not annual forecasts or additional regret scenarios.",
        f"Comparison period: {horizon} months. The supplied 12-month usage profile repeats; taxes and nonrecurring charges are excluded.",
        "Each plan uses its own rates during its original term, holding delivery rates constant as an assumption.",
        f"After expiration, charges escalate by {options.renewal_escalation_pct}% annually from the comparison start, using whole elapsed usage years. Renewal credits: {options.renewal_credit_policy}.",
        "Renewal is hypothetical, not general inflation or an available offer; original credit conditions may not be available. Future enrollment fees and renewal commitments are not modeled.",
        "Freshness uses a 365-day heuristic; recent documents do not establish live offer availability."]
    warnings = ["Live offer availability and address eligibility are unverified.",
        "Worst-case regret applies only to tested scenarios, not every possible outcome."]
    if options.baseline_plan_id is None:
        warnings.append("No current-plan baseline supplied; savings and switching payback are unavailable.")
    if excluded:
        warnings.append(f"{len(excluded)} plan(s) exceed your maximum contract length.")
    if renews:
        warnings.append("Some eligible plans require modeled renewal rates and credit terms. Multi-year estimates are uncertain.")
    if average_mode:
        assumptions = [a for a in assumptions if not a.startswith(("Credit probes", "Each plan uses", "After expiration"))]
        assumptions.append("Costs use each plan's mapped inclusive EFL averages, not tariff component bills. Renewal escalation applies to the inclusive rate; separate retain/drop credit settings do not apply.")
        warnings.append("Range-mapped EFL averages are an approximation. Fees and credits are embedded, not separately added or subtracted.")
    if custom_mode:
        assumptions = [a for a in assumptions if "inclusive" not in a]
        assumptions.append("Custom estimate: mapped EFL average supplies Energy; PDF base/usage fees and delivery are added and qualifying credits subtracted. Renewal escalates energy, base and delivery; retain/drop credits applies.")
        warnings = [w for w in warnings if "embedded, not separately" not in w]
        warnings.insert(0, "Custom formula repeats fee and credit effects embedded in EFL averages; totals are not actual tariff bills.")
    baseline = None
    if baseline_candidate:
        baseline_months, _ = project(baseline_candidate, usage, horizon, options.renewal_escalation_pct, options.renewal_credit_policy)
        baseline = {"plan_id": baseline_candidate.plan_id, "name": baseline_candidate.name,
            "annual_cost": annual(baseline_months[:12]), "horizon_cost": annual(baseline_months), "monthly_costs": [m.total for m in baseline_months],
            "basis": "Selected tariff modeled as a new full contract under the same repeated usage and renewal assumptions; remaining actual term and actual bills are unknown."}
    common = dict(comparison_horizon=horizon, policy_version="custom-efl-v4" if custom_mode else "efl-average-v3" if average_mode else "horizon-renewal-v2", scenarios=scenarios, options=options, assumptions=assumptions, warnings=warnings, baseline=baseline)
    if not candidates:
        return RecommendationResult(status="no_eligible_plans", confidence_reasons=["No plan meets the recommendation requirements."], **common)
    costs, months = {}, {}
    for c in candidates:
        months[c.plan_id] = {s["id"]: project(c, s["monthly_kwh"], horizon, s["renewal_escalation_pct"], s["renewal_credit_policy"])[0] for s in scenarios}
        costs[c.plan_id] = {key: annual(value) for key, value in months[c.plan_id].items()}
    candidates.sort(key=lambda c: (costs[c.plan_id]["supplied"], c.plan_id))
    minimums = {s["id"]: min(costs[c.plan_id][s["id"]] for c in candidates) for s in scenarios}
    analyses, evidence = [], []
    for c in candidates:
        references = []
        for i, ref in enumerate(c.evidence):
            reference_id = f"{c.plan_id}:source:{i}"
            evidence.append({"id": reference_id, "plan_id": c.plan_id, **ref})
            references.append(reference_id)
        calculation_id = f"{c.plan_id}:scenarios"
        evidence.append({"id": calculation_id, "plan_id": c.plan_id, "kind": "calculation",
                         "description": "Saved scenario results using mapped inclusive EFL averages." if c.pricing_basis == "efl_average" else "Saved scenario results and credit probes; computed using the existing monthly pricing engine."})
        references.append(calculation_id)
        results = [ScenarioCost(scenario_id=s["id"], annual_cost=annual(months[c.plan_id][s["id"]][:12]), horizon_cost=costs[c.plan_id][s["id"]],
            rank=1 + sum(costs[other.plan_id][s["id"]] < costs[c.plan_id][s["id"]] for other in candidates),
            regret=costs[c.plan_id][s["id"]] - minimums[s["id"]]) for s in scenarios]
        credit_analysis = credits(c, usage, months[c.plan_id])
        max_regret = max(r.regret for r in results)
        base_months, base_details = project(c, usage, horizon, options.renewal_escalation_pct, options.renewal_credit_policy)
        analyses.append(RecommendedPlan(plan_id=c.plan_id, name=c.name, term_months=c.term_months,
            estimated_annual_cost=annual(base_months[:12]), horizon_cost=costs[c.plan_id]["supplied"],
            annualized_cost=cash(costs[c.plan_id]["supplied"] * 12 / horizon),
            initial_term_cost=annual(base_months[:c.term_months]), modeled_renewal_cost=annual(base_months[c.term_months:]),
            horizon_monthly_costs=base_details,
            yearly_costs=[{"year": start // 12 + 1, "months": len(base_months[start:start+12]),
                          "cost": annual(base_months[start:start+12])} for start in range(0, horizon, 12)], scenario_results=results,
            max_scenario_regret=max_regret,
            additional_cost_at_supplied_usage=costs[c.plan_id]["supplied"] - minimums["supplied"],
            recommendation_reasons=[f"Estimated supplied-usage cost: ${costs[c.plan_id]['supplied']:,.2f}.",
                f"Maximum regret across tested scenarios: ${max_regret:,.2f}.",
                "Credits are embedded in EFL averages; separate credit analysis is unavailable." if c.pricing_basis == "efl_average" else f"Credits apply in {len(credit_analysis['qualifying_months'])} of {horizon} modeled months."],
            bill_credit_analysis=credit_analysis, evidence_refs=references))
    if baseline_candidate:
        baseline_refs = []
        for i, ref in enumerate(baseline_candidate.evidence):
            ref_id = f"{baseline_candidate.plan_id}:source:{i}"
            baseline_refs.append(ref_id)
            if not any(item['id'] == ref_id for item in evidence):
                evidence.append({"id": ref_id, "plan_id": baseline_candidate.plan_id, **ref})
        baseline["evidence_refs"] = baseline_refs
    best = analyses[0]
    resilient = min(analyses, key=lambda p: (p.max_scenario_regret, p.horizon_cost, p.plan_id))
    stable = all(r.regret == 0 for r in best.scenario_results)
    source_freshness = freshness(candidates[0], today or date.today())
    known_usage = options.usage_provenance in ("bills", "meter")
    confidence = "moderate" if data_mode == "pdf" and stable and known_usage and source_freshness == "recent" and len(candidates) > 1 and not renews else "low"
    reasons = [f"Usage provenance: {options.usage_provenance}; this is user-declared, not independently verified.",
        "The primary plan remains tied for cheapest or cheapest in all scenarios." if stable else "The cheapest plan changes across usage scenarios.",
        f"Primary plan document freshness: {source_freshness}.",
        "Prices use published EFL examples with user-defined range mapping." if average_mode else "Pricing passed catalog checks; these are not independent tariff approval." if data_mode == "pdf" else "Prices are synthetic demo fixtures.",
        "Live availability is unverified, so high confidence is not assigned."]
    if average_mode:
        confidence = "low"
        reasons.append("Mapped EFL example prices approximate other usage levels; these estimates are not validated tariff bills.")
    if renews:
        reasons.append("Renewal assumptions are needed for some alternatives; confidence is low.")
    if len(candidates) == 1:
        warnings.append("Only one plan qualifies. Zero regret reflects a single-option comparison, not evidence of market superiority.")
    if best.bill_credit_analysis["credit_loss_scenarios"]:
        warnings.append("The primary plan loses credits in at least one tested scenario.")
    if len(analyses) > 1 and analyses[1].horizon_cost - best.horizon_cost <= D("12"):
        warnings.append("The two lowest estimated horizon costs are within $12; treat them as close alternatives.")
    tradeoffs = [f"{resilient.name} has the lowest maximum scenario regret (${resilient.max_scenario_regret:,.2f}) and costs ${resilient.additional_cost_at_supplied_usage:,.2f} more at supplied usage."]
    conditions = []
    for other in analyses[1:]:
        previous = None
        for s in scenarios[:5]:
            difference = costs[best.plan_id][s["id"]] - costs[other.plan_id][s["id"]]
            if previous and ((previous[1] < 0 < difference) or (previous[1] > 0 > difference) or (difference == 0) != (previous[1] == 0)):
                conditions.append({"kind": "sampled_usage_bracket", "plan_ids": [best.plan_id, other.plan_id],
                    "lower_multiplier": previous[0]["multiplier"], "upper_multiplier": s["multiplier"],
                    "lower_cost_difference": previous[1], "upper_cost_difference": difference, "exact": False,
                    "description": "Cost preference changes between these tested usage levels; this is not an exact break-even point and there may be multiple crossings or credit cliffs."})
            previous = (s, difference)
    savings = None
    if baseline:
        gross = baseline["horizon_cost"] - best.horizon_cost
        first_year_gross = baseline["annual_cost"] - best.estimated_annual_cost
        fee = D("0.00") if best.plan_id == baseline["plan_id"] else options.switching_cost
        net = None if fee is None else cash(gross - fee)
        cumulative, running = [], D("0.00")
        if fee is not None:
            for before, after in zip(baseline["monthly_costs"], months[best.plan_id]["supplied"]):
                running += before - after.total
                cumulative.append(cash(running - fee))
        payback = None
        if fee is not None and best.plan_id != baseline["plan_id"]:
            payback = next((i + 1 for i in range(horizon) if all(v >= 0 for v in cumulative[i:])), None)
        savings = {"basis": "Estimated savings under supplied usage, not probability-weighted expected savings.",
            "gross_annual_savings": first_year_gross, "switching_cost": fee,
            "net_annual_savings": None if fee is None else cash(first_year_gross - fee),
            "gross_horizon_savings": gross, "net_horizon_savings": net,
            "sustained_payback_month": payback, "cumulative_net_savings": cumulative}
        conditions.append({"kind": "switching_cost_recovery", "month": payback,
            "description": f"First month after which cumulative net savings stay nonnegative through month {horizon}; null means unknown, not recovered, or no switch."})
        if fee is None:
            warnings.append("Switching cost is unknown; net savings and payback are unavailable.")
        if net is not None and net < 0:
            warnings.append("Switching costs exceed the estimated comparison-period savings; staying may cost less.")
        if baseline_candidate.term_months < 12:
            warnings.append("Baseline term does not cover the horizon.")
    return RecommendationResult(status="recommended", best_overall=best, top_3=analyses[:3],
        category_winners={"lowest_estimated_cost": best.plan_id, "lowest_scenario_regret": resilient.plan_id},
        plan_analyses=analyses, expected_savings=savings, confidence=confidence,
        confidence_components={"pricing_evidence": "mapped_efl_examples" if average_mode else "validated_catalog" if data_mode == "pdf" else "synthetic",
            "usage_quality": options.usage_provenance, "ranking_stable": stable, "modeled_renewal": renews,
            "document_freshness": source_freshness, "availability": "unverified"},
        confidence_reasons=reasons, key_tradeoffs=tradeoffs, break_even_conditions=conditions,
        evidence_refs=evidence, **common)

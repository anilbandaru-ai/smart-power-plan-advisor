# Rough estimates and editable assumptions

Compare plans as usual. After the calculated-cost ranking, **Rough cost estimates**
shows separate illustrations for plans whose rules cannot yet support that ranking.
Notes, availability, original exclusions and monthly totals accompany every plan.
Change its numerical assumptions and click **Compare plans** again. Until then,
the card says that its displayed costs use the previous assumptions. Reset clears
all overrides. Changing ZIP or utility also clears them.

Rough results never become the recommended winner or a savings baseline. A hidden
or inactive offer is labeled hypothetical. If only rough estimates are possible,
the result has no recommendation but still displays and saves those illustrations.
Saved comparisons restore their assumptions; source changes can require resetting
old controls before making a new comparison.

## Methods

- **Benchmark:** Convert published average cents/kWh into total bills at 500,
  1000 and 2000 kWh. Interpolate bills between those points. Outside that range,
  project the nearest average rate and show an extrapolation warning. A percentage
  adjustment is a sensitivity scenario. Known PDF credit thresholds are preserved
  by interpolating pre-credit bills, then applying the discrete credit.
- **Flat / threshold:** Apply reviewed source charges and a stated threshold credit.
  API marketing-derived credits remain assumptions until their full terms are
  validated; original ranking eligibility stays unchanged.
- **Free usage:** Apply the editable percentage of usage in free periods. Waive
  energy on that share; the separate delivery-waiver percentage determines the
  variable delivery benefit. Base and fixed delivery remain. This models a share,
  not interval selection or actual billing-day counts.
- **Seasonal:** Apply the energy discount in the selected billing months. A start
  later than the end wraps across year end. Seasonal-credit profiles apply the
  extra credit only when the ordinary usage threshold qualifies. Combined
  night/summer profiles discount the remaining daytime energy in summer.
- **Solar:** Entered consumption means grid imports. Subtract assumed monthly
  exports × assumed buyback rate. Floor the bill at zero, with no modeled rollover
  or payout. Both export assumptions start at zero; other solar-branded plans do
  not automatically qualify for buyback.
- **Reward:** Default reward realization is zero. If changed, spread the redeemed
  fraction of the advertised energy-charge reward across months. This is an
  equivalent economic value scenario, not an invoice credit.
- **Tiered:** Charge marginal usage blocks separately, rather than apply the
  cheaper tier to all usage. The reviewed Reliant profiles retain this distinction.
- **Short / variable:** Hold published rates constant for the twelve-month
  illustration by default. Apply the editable bill-change percentage after the
  known term or first variable cycle; future prices are not guaranteed.

Every method rounds the final monthly scenario total to cents, then sums twelve
months. These are illustrations under the displayed assumptions, not bill quotes.
The [plan-by-plan review](plan-rule-review.md) records all 63 current source records,
including rate conflicts and why some plans use benchmarks instead of components.

## API contract

`GET /api/catalog/records` includes `rough_estimate` capability: support status,
method, source fingerprint, review status, notes and allowed parameter definitions.
`POST /api/comparisons` accepts an optional map:

```json
{
  "rough_assumptions": {
    "catalog-record-id": {"free_usage_percent": "35", "delivery_waiver_percent": "0"}
  }
}
```

Include the usual ZIP, source, utility (if required) and twelve monthly usage
values. Use actual IDs and only parameters exposed for that record. Unknown IDs,
unknown parameters and invalid ranges receive 422. All inputs are recalculated
server-side; the browser never supplies prices. The response adds `rough_estimates`
with monthly/annual totals, assumptions used, parameter definitions, method,
source fingerprint/revision, notes, availability and original pricing issues.
Original saved results without this field still load.

The trusted [review registry](../backend/catalog/plan_reviews.json) binds profiles
to source versions. Future providers reuse the method engine with a new reviewed
adapter/profile, rather than embedding provider-specific branches in arithmetic.

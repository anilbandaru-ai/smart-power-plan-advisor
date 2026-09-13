"""Explicit hypothetical renewal projections using each plan's own pricing calculator."""
from decimal import Decimal, ROUND_HALF_UP

D = Decimal


def cash(value):
    return value.quantize(D('0.01'), rounding=ROUND_HALF_UP)


def project(candidate, usage, horizon, escalation, credit_policy):
    months, details = [], []
    for index in range(horizon):
        original = candidate.calculate(usage[index % 12], index % 12 + 1)
        renewal = index >= candidate.term_months
        factor = (1 + escalation / 100) ** (index // 12) if renewal else D(1)
        energy, base, delivery = (cash(getattr(original, field) * factor) for field in ('energy', 'base_fee', 'delivery'))
        credit = D('0.00') if renewal and credit_policy == 'drop' else original.credit
        month = original.model_copy(update={'month': index + 1, 'energy': energy, 'base_fee': base,
            'delivery': delivery, 'credit': credit, 'total': cash(energy + base + delivery - credit)})
        if original.pricing_basis == 'efl_average':
            rate = original.average_price_cents * factor
            inclusive = cash(original.kwh * rate / 100)
            month = original.model_copy(update={'month': index + 1, 'energy': inclusive,
                'total': inclusive, 'average_price_cents': rate})
        if original.pricing_basis == 'custom_efl':
            rate = original.average_price_cents * factor
            energy = cash(original.kwh * rate / 100)
            month = month.model_copy(update={'energy': energy, 'average_price_cents': rate,
                'total': cash(energy + base + delivery - credit)})
        months.append(month)
        details.append({**month.model_dump(), 'basis': 'modeled_renewal' if renewal else 'document_terms',
                        'rate_multiplier': factor})
    return months, details


def attach_projections(results, candidates, request):
    horizon = request.recommendation_options.max_contract_months or 12
    options = request.recommendation_options
    by_id = {candidate.plan_id: candidate for candidate in candidates}
    for result in results:
        months, details = project(by_id[result.plan_id], request.monthly_kwh, horizon,
                                  options.renewal_escalation_pct, options.renewal_credit_policy)
        result.horizon_cost = sum((month.total for month in months), D('0.00'))
        result.comparison_horizon = horizon
        result.horizon_monthly_costs = details
    results.sort(key=lambda result: (result.horizon_cost, result.plan_id))

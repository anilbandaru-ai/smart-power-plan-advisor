"""Deterministic calculation and comparison; no LLM or network dependencies."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from backend.integrations import PlanSource, DEMO_ZIP_PLAN_IDS
from backend.models import ComparisonRequest, ComparisonResult, MonthlyCost, Plan, PlanComparison


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_month(plan: Plan, kwh: Decimal, month: int) -> MonthlyCost:
    energy = money(kwh * plan.energy_rate)
    delivery = money(kwh * plan.delivery_rate + plan.delivery_fee)
    base_fee = money(plan.base_fee)
    credit = money(plan.credit_amount) if (
        plan.credit_threshold is not None and kwh >= plan.credit_threshold
    ) else Decimal("0.00")
    return MonthlyCost(
        month=month, kwh=kwh, energy=energy, base_fee=base_fee,
        delivery=delivery, credit=credit,
        total=money(energy + delivery + base_fee - credit),
    )


def compare(request: ComparisonRequest, source: PlanSource) -> ComparisonResult:
    candidates = DEMO_ZIP_PLAN_IDS.get(request.zip_code, ())
    if not candidates:
        raise ValueError("This ZIP code is not covered by the demo lookup.")
    plans = [plan for plan in source.list_plans() if plan.id in candidates]
    if not plans:
        raise ValueError("No demo plans are available for this ZIP code.")
    results = []
    for plan in plans:
        months = [calculate_month(plan, usage, i + 1) for i, usage in enumerate(request.monthly_kwh)]
        annual = sum((month.total for month in months), Decimal("0.00"))
        credited_months = sum(month.credit > 0 for month in months)
        explanation = (
            f"Estimated 12-month cost: ${annual:,.2f}, calculated separately for each supplied month. "
            f"Includes energy, base fees and demo delivery charges. "
            f"A bill credit applies in {credited_months} of 12 months."
        )
        results.append(PlanComparison(
            plan_id=plan.id, name=plan.name, term_months=plan.term_months,
            annual_cost=annual, monthly_costs=months,
            explanation=explanation, source=plan.source,
        ))
    results.sort(key=lambda result: (result.annual_cost, result.plan_id))
    return ComparisonResult(
        id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat(),
        zip_code=request.zip_code,
        assumptions=[
            "Synthetic demonstration plans and rates; these are not available offers.",
            "All prices are USD. Rates and delivery charges stay constant for 12 months.",
            "Taxes, enrollment fees and early termination fees are excluded.",
            "Plan coverage uses an in-memory demo ZIP mapping; address eligibility is not verified.",
            "Monthly energy, delivery, base fee and credit amounts round to cents before summing.",
        ],
        recommendations=results,
    )

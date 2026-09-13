"""User-defined EFL reference bands used as inclusive cost approximations."""
from decimal import Decimal, ROUND_HALF_UP
from backend.models import MonthlyCost


def calculate_average(plan, usage, month):
    examples = sorted(plan.examples, key=lambda example: example.kwh)
    if not examples or len({e.kwh for e in examples}) != len(examples):
        raise ValueError("Unique published EFL average-price examples are required")
    selected = examples[0]
    for example in examples:
        if usage > example.kwh:
            selected = example
    total = (usage * selected.cents_per_kwh / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return MonthlyCost(month=month, kwh=usage, energy=total, total=total,
        base_fee=Decimal("0.00"), delivery=Decimal("0.00"), credit=Decimal("0.00"),
        pricing_basis="efl_average", average_price_cents=selected.cents_per_kwh)


def calculate_custom(plan, usage, month):
    """Authorized custom estimate; the mapped average substitutes for energy only."""
    from backend.catalog.pricing import calculate
    charges = calculate(plan, usage, month)
    average = calculate_average(plan, usage, month)
    return charges.model_copy(update={"pricing_basis": "custom_efl",
        "average_price_cents": average.average_price_cents, "energy": average.energy,
        "total": average.energy + charges.base_fee + charges.delivery - charges.credit})

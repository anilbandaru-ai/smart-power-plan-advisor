from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


NonNegative = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tdu: str = Field(min_length=1, max_length=60)
    monthly_kwh: list[NonNegative] = Field(min_length=12, max_length=12)


class Plan(BaseModel):
    id: str
    name: str
    tdu: str
    energy_rate: NonNegative
    base_fee: NonNegative
    delivery_rate: NonNegative
    delivery_fee: NonNegative
    credit_threshold: NonNegative | None = None
    credit_amount: NonNegative = Decimal("0")
    term_months: int = 12
    source: str


class MonthlyCost(BaseModel):
    month: int
    kwh: Decimal
    energy: Decimal
    base_fee: Decimal
    delivery: Decimal
    credit: Decimal
    total: Decimal


class PlanComparison(BaseModel):
    plan_id: str
    name: str
    term_months: int
    annual_cost: Decimal
    monthly_costs: list[MonthlyCost]
    explanation: str
    source: str


class ComparisonResult(BaseModel):
    id: str
    created_at: str
    data_mode: str = "demo"
    tdu: str
    assumptions: list[str]
    recommendations: list[PlanComparison]

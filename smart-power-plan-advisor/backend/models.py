from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from backend.recommendation_models import RecommendationOptions, RecommendationResult


ZipCode = Annotated[str, Field(pattern=r"^[0-9]{5}$", min_length=5, max_length=5)]


NonNegative = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=4)]


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zip_code: ZipCode
    recommendation_options: RecommendationOptions = Field(default_factory=RecommendationOptions)
    data_source: Literal["demo", "pdf"] = "demo"
    monthly_kwh: list[NonNegative] = Field(min_length=12, max_length=12)


class Plan(BaseModel):
    id: str
    name: str
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
    source_url: str | None = None
    source_revision: str | None = None
    tdu_source: dict | None = None


class ComparisonResult(BaseModel):
    id: str
    created_at: str
    data_mode: str = "demo"
    zip_code: ZipCode | None = None  # Legacy snapshots did not store ZIP.
    assumptions: list[str]
    recommendations: list[PlanComparison]
    excluded_plans: list[dict] = Field(default_factory=list)
    recommendation_result: RecommendationResult | None = None

from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecommendationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comparison_horizon: int | None = Field(default=None, ge=12, le=120)
    exact_contract_months: int | None = Field(default=None, ge=12, le=120)
    exclude_bill_credit_plans: bool = False

    @model_validator(mode="after")
    def consistent_contract(self):
        if self.exact_contract_months and self.max_contract_months and self.exact_contract_months > self.max_contract_months:
            raise ValueError("Exact contract length exceeds the maximum contract length")
        return self

    renewal_escalation_pct: Decimal = Field(default=Decimal("5"), ge=0, le=30, max_digits=4, decimal_places=2)
    renewal_credit_policy: Literal["retain", "drop"] = "retain"
    usage_provenance: Literal["unknown", "estimated", "bills", "meter"] = "unknown"
    max_contract_months: int | None = Field(default=None, ge=12, le=120)
    baseline_plan_id: str | None = Field(default=None, min_length=1, max_length=200)
    switching_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class ScenarioCost(BaseModel):
    scenario_id: str
    annual_cost: Decimal
    horizon_cost: Decimal | None = None
    rank: int
    regret: Decimal


class RecommendedPlan(BaseModel):
    plan_id: str
    name: str
    term_months: int
    estimated_annual_cost: Decimal
    horizon_cost: Decimal | None = None
    annualized_cost: Decimal | None = None
    initial_term_cost: Decimal | None = None
    modeled_renewal_cost: Decimal | None = None
    horizon_monthly_costs: list[dict] = Field(default_factory=list)
    yearly_costs: list[dict] = Field(default_factory=list)
    recommendation_reasons: list[str]
    scenario_results: list[ScenarioCost]
    max_scenario_regret: Decimal
    additional_cost_at_supplied_usage: Decimal
    bill_credit_analysis: dict
    evidence_refs: list[str]


class RecommendationResult(BaseModel):
    status: Literal["recommended", "no_eligible_plans"]
    best_overall: RecommendedPlan | None = None
    top_3: list[RecommendedPlan] = Field(default_factory=list)
    category_winners: dict[str, str | None] = Field(default_factory=dict)
    plan_analyses: list[RecommendedPlan] = Field(default_factory=list)
    baseline: dict | None = None
    expected_savings: dict | None = None
    confidence: Literal["low", "moderate", "high"] = "low"
    confidence_components: dict = Field(default_factory=dict)
    confidence_reasons: list[str] = Field(default_factory=list)
    key_tradeoffs: list[str] = Field(default_factory=list)
    break_even_conditions: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[dict] = Field(default_factory=list)
    scenarios: list[dict] = Field(default_factory=list)
    policy_version: str = "cost-first-scenario-regret-v1"
    comparison_horizon: int = 12
    assumptions: list[str] = Field(default_factory=list)
    options: RecommendationOptions = Field(default_factory=RecommendationOptions)

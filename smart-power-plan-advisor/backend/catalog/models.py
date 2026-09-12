from decimal import Decimal
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema


# Simple string wire schema avoids provider grammar issues with Decimal union patterns.
# Pydantic still validates and converts these values to Decimal locally.
DecimalValue = Annotated[Decimal, WithJsonSchema({"type": "string"})]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(Strict):
    page: int | None = Field(default=None, ge=1)
    url: str | None = None
    quote: str = Field(min_length=3, max_length=4000)


class Fact(Strict):
    value: str
    evidence: Evidence


class Component(Strict):
    kind: Literal['energy', 'base', 'delivery_fixed', 'delivery_energy', 'usage_charge', 'credit']
    amount: DecimalValue = Field(ge=0, max_digits=14, decimal_places=6)
    unit: Literal['cents_per_kwh', 'usd_per_month']
    minimum_kwh: DecimalValue | None
    minimum_inclusive: bool
    maximum_kwh: DecimalValue | None
    maximum_inclusive: bool
    evidence: Evidence


class Example(Strict):
    kwh: int = Field(gt=0)
    cents_per_kwh: DecimalValue = Field(ge=0)
    evidence: Evidence


class TduSource(Strict):
    url: str
    service_area: str
    published_on: str
    date_label: str
    fetched_at: str
    snapshot: str
    sha256: str
    monthly_usd: DecimalValue
    cents_per_kwh: DecimalValue


class TduLookup(Strict):
    candidate_url: str | None = None
    status: str
    detail: str
    source: TduSource | None = None


class ExtractedPlan(Strict):
    tdu_lookup: TduLookup | None = None
    name: Fact | None
    provider: Fact | None
    service_area: Fact | None
    issue_date: Fact | None
    product_type: Fact | None
    contract_term: Fact | None
    termination_terms: Fact | None
    components: list[Component] = Field(max_length=30)
    examples: list[Example] = Field(max_length=10)
    unsupported_rules: list[str] = Field(max_length=20)
    extraction_notes: list[str] = Field(max_length=20)

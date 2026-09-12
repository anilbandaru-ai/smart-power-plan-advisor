"""The plan source is the boundary for a future live-data integration."""

import json
from pathlib import Path
from typing import Protocol

from backend.models import Plan


# Synthetic coverage only; these plan IDs do not establish real eligibility.
DEMO_ZIP_PLAN_IDS = {
    "75201": ("demo-oncor-simple", "demo-oncor-credit"),
    "75001": ("demo-oncor-simple", "demo-oncor-credit"),
    "77002": ("demo-centerpoint-simple", "demo-centerpoint-credit"),
    "77007": ("demo-centerpoint-simple", "demo-centerpoint-credit"),
}


class PlanSource(Protocol):
    def list_plans(self) -> list[Plan]: ...


class JsonPlanSource:
    def __init__(self, path: Path):
        self.path = path

    def list_plans(self) -> list[Plan]:
        return [Plan.model_validate(item) for item in json.loads(self.path.read_text())]

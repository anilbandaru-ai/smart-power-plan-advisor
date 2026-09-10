"""The plan source is the boundary for a future live-data integration."""

import json
from pathlib import Path
from typing import Protocol

from backend.models import Plan


class PlanSource(Protocol):
    def list_plans(self) -> list[Plan]: ...


class JsonPlanSource:
    def __init__(self, path: Path):
        self.path = path

    def list_plans(self) -> list[Plan]:
        return [Plan.model_validate(item) for item in json.loads(self.path.read_text())]

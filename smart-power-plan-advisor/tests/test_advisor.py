import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import ROOT, create_app
from backend.integrations import JsonPlanSource
from backend.models import ComparisonRequest
from backend.services import calculate_month, compare


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.source = JsonPlanSource(ROOT / "data" / "plans.json")

    def test_credit_threshold(self):
        plan = next(plan for plan in self.source.list_plans() if plan.id == "demo-oncor-credit")
        for usage, expected in [("999", "189.82"), ("1000", "150.00"), ("1001", "150.18")]:
            with self.subTest(usage=usage):
                self.assertEqual(calculate_month(plan, Decimal(usage), 1).total, Decimal(expected))

    def test_variable_months_are_not_replaced_with_average(self):
        result = compare(ComparisonRequest(tdu="Oncor", monthly_kwh=[500, 1500] * 6), self.source)
        self.assertEqual(result.recommendations[0].plan_id, "demo-oncor-simple")
        self.assertEqual(result.recommendations[0].annual_cost, Decimal("1920.00"))
        self.assertEqual(result.recommendations[1].annual_cost, Decimal("2040.00"))
        self.assertTrue(all("oncor" in plan.plan_id for plan in result.recommendations))


class ApiTests(unittest.TestCase):
    def test_comparison_persists_across_app_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.sqlite3"
            with TestClient(create_app(db_path)) as client:
                self.assertEqual(client.get("/").status_code, 200)
                self.assertEqual(client.get("/static/app.js").status_code, 200)
                self.assertEqual(client.get("/api/health").json()["status"], "ok")
                self.assertEqual(len(client.get("/api/plans").json()["plans"]), 4)
                response = client.post("/api/comparisons", json={"tdu": "Oncor", "monthly_kwh": [1000] * 12})
                self.assertEqual(response.status_code, 201)
                result = response.json()
                self.assertEqual(result["recommendations"][0]["annual_cost"], "1800.00")
            with TestClient(create_app(db_path)) as client:
                self.assertEqual(client.get(f'/api/comparisons/{result["id"]}').json(), result)
                self.assertEqual(client.get('/api/comparisons/00000000-0000-0000-0000-000000000000').status_code, 404)

    def test_rejects_invalid_or_unsupported_input(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory) / "test.sqlite3")) as client:
                for payload in [
                    {"tdu": "Unknown", "monthly_kwh": [1000] * 12},
                    {"tdu": "Oncor", "monthly_kwh": [1000]},
                    {"tdu": "Oncor", "monthly_kwh": [-1] * 12},
                    {"tdu": "Oncor", "monthly_kwh": ["NaN"] * 12},
                ]:
                    with self.subTest(payload=payload):
                        self.assertEqual(client.post("/api/comparisons", json=payload).status_code, 422)


if __name__ == "__main__":
    unittest.main()

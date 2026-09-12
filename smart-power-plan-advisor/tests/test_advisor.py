import json
import sqlite3
import tempfile
from unittest.mock import patch
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
        result = compare(ComparisonRequest(zip_code="75201", monthly_kwh=[500, 1500] * 6), self.source)
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
                response = client.post("/api/comparisons", json={"zip_code": "75201", "monthly_kwh": [1000] * 12})
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
                    {"zip_code": "75201", "tdu": "Unknown", "monthly_kwh": [1000] * 12},
                    {"zip_code": "75201", "monthly_kwh": [1000]},
                    {"zip_code": "75201", "monthly_kwh": [-1] * 12},
                    {"zip_code": "75201", "monthly_kwh": ["NaN"] * 12},
                ]:
                    with self.subTest(payload=payload):
                        self.assertEqual(client.post("/api/comparisons", json=payload).status_code, 422)


class ZipTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "test.sqlite3"
        self.client = self.enterContext(TestClient(create_app(self.db_path)))

    def test_zip_only_filtering_and_validation(self):
        for zip_code, prefix in [("75201", "oncor"), ("75001", "oncor"), ("77002", "centerpoint"), ("77007", "centerpoint")]:
            result = self.client.post("/api/comparisons", json={"zip_code": zip_code, "monthly_kwh": [1000] * 12})
            self.assertEqual(result.status_code, 201)
            self.assertNotIn("tdu", result.json())
            self.assertEqual(len(result.json()["recommendations"]), 2)
            self.assertTrue(all(prefix in plan["plan_id"] for plan in result.json()["recommendations"]))
        for value in [None, 75201, "1234", "123456", "abcde", "99999", "75201\n"]:
            self.assertEqual(self.client.post("/api/comparisons", json={"zip_code": value, "monthly_kwh": [1000] * 12}).status_code, 422)
        self.assertEqual(self.client.post("/api/comparisons", json={"monthly_kwh": [1000] * 12}).status_code, 422)

    def test_removed_area_resources(self):
        self.assertEqual(self.client.get("/api/service-areas?zip_code=75201").status_code, 404)
        catalog = self.client.get("/api/plans").json()
        self.assertNotIn("tdus", catalog)
        self.assertTrue(all("tdu" not in plan for plan in catalog["plans"]))
        page = self.client.get("/").text
        self.assertNotIn('id="tdu"', page)
        self.assertNotIn('id="lookup-area"', page)
        self.assertEqual(self.client.post("/api/comparisons", json={"zip_code": "75201", "tdu": "Oncor", "monthly_kwh": [1000] * 12}).status_code, 422)

    def test_leading_zero_and_missing_catalog_entries(self):
        from backend.integrations import DEMO_ZIP_PLAN_IDS
        with patch.dict(DEMO_ZIP_PLAN_IDS, {"00001": ("demo-oncor-simple", "missing"), "00002": ("missing",)}):
            result = self.client.post("/api/comparisons", json={"zip_code": "00001", "monthly_kwh": [1000] * 12})
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()["zip_code"], "00001")
            self.assertEqual(len(result.json()["recommendations"]), 1)
            self.assertEqual(self.client.post("/api/comparisons", json={"zip_code": "00002", "monthly_kwh": [1000] * 12}).status_code, 422)

    def test_legacy_snapshot_still_loads_without_zip(self):
        result = self.client.post("/api/comparisons", json={"zip_code": "75201", "monthly_kwh": [1000] * 12}).json()
        result.pop("zip_code")
        connection = sqlite3.connect(self.db_path)
        try:
            with connection:
                connection.execute("UPDATE comparisons SET payload = ? WHERE id = ?", (json.dumps({**result, "tdu": "Oncor"}), result["id"]))
        finally:
            connection.close()
        response = self.client.get(f'/api/comparisons/{result["id"]}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {**result, "zip_code": None})


if __name__ == "__main__":
    unittest.main()

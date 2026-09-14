"""API regressions against the supplied local PostgreSQL/Redis stack.

Run with RUN_INTEGRATION_TESTS=1 and TEST_API_URL; see README.md.
Only uniquely named test properties/reservations are inserted and removed.
"""

import os
import unittest
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import psycopg2


@unittest.skipUnless(os.getenv("RUN_INTEGRATION_TESTS") == "1", "requires local seeded stack")
class DashboardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = httpx.Client(
            base_url=os.getenv("TEST_API_URL", "http://localhost:8000"), timeout=15
        )
        cls.db = psycopg2.connect(os.getenv("TEST_DATABASE_URL") or os.environ["DATABASE_URL"])
        cls.db.autocommit = True
        cls.headers = {}
        for tenant, email, password in (
            ("tenant-a", "sunset@propertyflow.com", "client_a_2024"),
            ("tenant-b", "ocean@propertyflow.com", "client_b_2024"),
        ):
            response = cls.client.post("/api/v1/auth/login", json={"email": email, "password": password})
            if response.status_code != 200:
                raise AssertionError(f"Fixture login failed: {response.status_code}")
            cls.headers[tenant] = {"Authorization": f"Bearer {response.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.db.close()

    def setUp(self):
        self.created_properties = []

    def tearDown(self):
        with self.db.cursor() as cursor:
            for property_id, tenant in self.created_properties:
                cursor.execute("DELETE FROM reservations WHERE property_id = %s AND tenant_id = %s", (property_id, tenant))
                cursor.execute("DELETE FROM properties WHERE id = %s AND tenant_id = %s", (property_id, tenant))

    def property(self, timezone="Europe/Paris", tenant="tenant-a", property_id=None):
        property_id = property_id or f"regression-{uuid.uuid4().hex}"
        with self.db.cursor() as cursor:
            cursor.execute(
                "INSERT INTO properties (id, tenant_id, name, timezone) VALUES (%s, %s, %s, %s)",
                (property_id, tenant, "Regression fixture", timezone),
            )
        self.created_properties.append((property_id, tenant))
        return property_id

    def reservation(self, property_id, at, amount, tenant="tenant-a", currency="USD"):
        check_in = datetime.fromisoformat(at)
        with self.db.cursor() as cursor:
            cursor.execute(
                """INSERT INTO reservations
                (id, property_id, tenant_id, check_in_date, check_out_date, total_amount, currency)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (f"regression-{uuid.uuid4().hex}", property_id, tenant, check_in,
                 check_in + timedelta(days=1), Decimal(amount), currency),
            )

    def summary(self, tenant, property_id, year=2024, month=3, status=200):
        params = {"property_id": property_id}
        if year is not None:
            params["year"] = year
        if month is not None:
            params["month"] = month
        response = self.client.get("/api/v1/dashboard/summary", params=params, headers=self.headers[tenant])
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_provided_accounts_and_property_names(self):
        expected = {
            "tenant-a": {"prop-001": "Beach House Alpha", "prop-002": "City Apartment Downtown", "prop-003": "Country Villa Estate"},
            "tenant-b": {"prop-001": "Mountain Lodge Beta", "prop-004": "Lakeside Cottage", "prop-005": "Urban Loft Modern"},
        }
        for tenant, properties in expected.items():
            with self.subTest(tenant=tenant):
                response = self.client.get("/api/v1/dashboard/properties", headers=self.headers[tenant])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual({p["id"]: p["name"] for p in response.json()["properties"]}, properties)
                identity = self.client.get("/api/v1/auth/me", headers=self.headers[tenant])
                self.assertEqual(identity.status_code, 200)
                self.assertEqual(identity.json()["tenant_id"], tenant)

    def test_seeded_march_totals_and_counts(self):
        fixtures = {
            "tenant-a": {"prop-001": ("2250.00", 4), "prop-002": ("4975.50", 4), "prop-003": ("6100.50", 2)},
            "tenant-b": {"prop-001": ("0.00", 0), "prop-004": ("1776.50", 4), "prop-005": ("3256.00", 3)},
        }
        for tenant, properties in fixtures.items():
            total = Decimal("0")
            for property_id, (amount, count) in properties.items():
                with self.subTest(tenant=tenant, property=property_id):
                    report = self.summary(tenant, property_id)
                    self.assertEqual(report["total_revenue"], amount)
                    self.assertEqual(report["reservations_count"], count)
                    self.assertEqual(report["currency"], "USD")
                    self.assertEqual((report["year"], report["month"]), (2024, 3))
                    total += Decimal(report["total_revenue"])
            self.assertEqual(total, Decimal("13326.00" if tenant == "tenant-a" else "5032.50"))

    def test_shared_property_cache_in_both_orders(self):
        for order in (("tenant-a", "tenant-b"), ("tenant-b", "tenant-a")):
            shared_id = self.property()
            self.property("America/New_York", "tenant-b", shared_id)
            self.reservation(shared_id, "2024-03-15T12:00:00+00:00", "2250.00")
            for tenant in order * 3:
                with self.subTest(order=order, tenant=tenant):
                    report = self.summary(tenant, shared_id)
                    self.assertEqual(report["total_revenue"], "2250.00" if tenant == "tenant-a" else "0.00")

    def test_monthly_annual_and_all_time_cache_separation(self):
        self.assertEqual(self.summary("tenant-a", "prop-001", month=2)["total_revenue"], "0.00")
        self.assertEqual(self.summary("tenant-a", "prop-001")["total_revenue"], "2250.00")
        self.assertEqual(self.summary("tenant-a", "prop-001", month=None)["total_revenue"], "2250.00")
        self.assertEqual(self.summary("tenant-a", "prop-001", year=None, month=None)["total_revenue"], "2250.00")

    def test_dst_aware_half_open_march_boundaries(self):
        fixtures = (
            ("Europe/Paris", "2024-02-29T23:00:00+00:00", "2024-03-31T22:00:00+00:00"),
            ("America/New_York", "2024-03-01T05:00:00+00:00", "2024-04-01T04:00:00+00:00"),
        )
        for timezone, lower, upper in fixtures:
            with self.subTest(timezone=timezone):
                prop = self.property(timezone)
                start, end = datetime.fromisoformat(lower), datetime.fromisoformat(upper)
                for at, amount in ((start - timedelta(microseconds=1), "1"), (start, "2"), (end - timedelta(microseconds=1), "4"), (end, "8")):
                    self.reservation(prop, at.isoformat(), amount)
                report = self.summary("tenant-a", prop)
                self.assertEqual(report["total_revenue"], "6.00")
                self.assertEqual(report["reservations_count"], 2)

    def test_annual_boundary_and_december_rollover(self):
        prop = self.property()
        for at, amount in (
            ("2023-12-31T22:59:59+00:00", "1"),
            ("2023-12-31T23:00:00+00:00", "2"),
            ("2024-12-31T22:59:59+00:00", "4"),
            ("2024-12-31T23:00:00+00:00", "8"),
        ):
            self.reservation(prop, at, amount)
        self.assertEqual(self.summary("tenant-a", prop, month=None)["total_revenue"], "6.00")
        self.assertEqual(self.summary("tenant-a", prop, month=12)["total_revenue"], "4.00")
        self.assertEqual(self.summary("tenant-a", prop, year=2025, month=1)["total_revenue"], "8.00")

    def test_aggregate_before_rounding(self):
        prop = self.property()
        for amount in ("333.333", "333.333", "333.334"):
            self.reservation(prop, "2024-03-15T12:00:00+00:00", amount)
        self.assertEqual(self.summary("tenant-a", prop)["total_revenue"], "1000.00")

    def test_rounding_ties_and_negative_adjustments(self):
        for amount, expected in (("0.005", "0.01"), ("-0.005", "-0.01"), ("2.675", "2.68")):
            with self.subTest(amount=amount):
                prop = self.property()
                self.reservation(prop, "2024-03-15T12:00:00+00:00", amount)
                self.assertEqual(self.summary("tenant-a", prop)["total_revenue"], expected)

    def test_different_currencies_remain_separate(self):
        prop = self.property()
        self.reservation(prop, "2024-03-15T12:00:00+00:00", "100.01", currency="USD")
        self.reservation(prop, "2024-03-15T12:00:00+00:00", "50.02", currency="EUR")
        report = self.summary("tenant-a", prop)
        self.assertIsNone(report["total_revenue"])
        self.assertIsNone(report["currency"])
        self.assertEqual({g["currency"]: g["total_revenue"] for g in report["totals_by_currency"]}, {"USD": "100.01", "EUR": "50.02"})
        self.assertEqual(report["reservations_count"], 2)

    def test_foreign_and_missing_properties_are_not_accessible(self):
        self.summary("tenant-b", "prop-002", status=404)
        self.summary("tenant-a", "prop-004", status=404)
        self.summary("tenant-a", "does-not-exist", status=404)

    def test_period_validation(self):
        for year, month in ((2024, 0), (2024, 13), (0, 3), (9999, 3), (None, 3)):
            with self.subTest(year=year, month=month):
                self.summary("tenant-a", "prop-001", year=year, month=month, status=422)

    def test_untrusted_tenant_header_does_not_change_account(self):
        response = self.client.get(
            "/api/v1/dashboard/summary",
            params={"property_id": "prop-001", "year": 2024, "month": 3},
            headers={**self.headers["tenant-b"], "X-Simulated-Tenant": "tenant-a"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total_revenue"], "0.00")


if __name__ == "__main__":
    unittest.main()

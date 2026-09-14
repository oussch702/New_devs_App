"""Focused failure-path regressions; database/cache substitutes stay process-local."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.v1 import dashboard
from app.core.database_pool import DatabasePool
from app.services import cache
from app.services.reservations import PropertyNotFoundError, revenue_period_bounds


class RevenueCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.report = {
            "property_id": "prop-001", "timezone": "Europe/Paris", "year": 2024,
            "month": 3, "reservations_count": 4, "total_revenue": "2250.00",
            "currency": "USD", "totals_by_currency": [
                {"currency": "USD", "total_revenue": "2250.00", "reservations_count": 4}
            ],
        }
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=object())
        session_context.__aexit__ = AsyncMock(return_value=False)
        self.redis = SimpleNamespace(get=AsyncMock(return_value=None), setex=AsyncMock())
        self.authorize = AsyncMock(return_value={"id": "prop-001", "name": "Beach", "timezone": "Europe/Paris"})
        self.calculate = AsyncMock(return_value=self.report)
        for target, replacement in (
            ("db_pool", SimpleNamespace(get_session=MagicMock(return_value=session_context))),
            ("redis_client", self.redis),
            ("require_property", self.authorize),
            ("calculate_total_revenue", self.calculate),
        ):
            patcher = patch.object(cache, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def summary(self):
        return await cache.get_revenue_summary("prop-001", "tenant-a", 2024, 3)

    async def test_valid_cache_hit_still_authorizes_property(self):
        self.redis.get.return_value = json.dumps({"tenant_id": "tenant-a", "summary": self.report})
        self.assertEqual(await self.summary(), self.report)
        self.authorize.assert_awaited_once()
        self.calculate.assert_not_awaited()

    async def test_redis_connection_failure_returns_actual_database_result(self):
        self.redis.get.side_effect = RedisConnectionError("unavailable")
        self.redis.setex.side_effect = RedisConnectionError("unavailable")
        self.assertEqual(await self.summary(), self.report)
        self.calculate.assert_awaited_once()

    async def test_corrupt_or_malformed_cache_uses_database(self):
        missing_count = {key: value for key, value in self.report.items() if key != "reservations_count"}
        for cached in (
            "not json", "[]", "null",
            json.dumps({"tenant_id": "tenant-a", "summary": missing_count}),
            json.dumps({"tenant_id": "tenant-a", "summary": {**self.report, "totals_by_currency": "invalid"}}),
        ):
            with self.subTest(cached=cached):
                self.redis.get.return_value = cached
                self.assertEqual(await self.summary(), self.report)

    async def test_wrong_tenant_or_period_cache_is_ignored(self):
        for tenant, report in (
            ("tenant-b", self.report),
            ("tenant-a", {**self.report, "month": 2}),
            ("tenant-a", {**self.report, "year": None, "month": None}),
        ):
            self.redis.get.return_value = json.dumps({"tenant_id": tenant, "summary": report})
            self.assertEqual(await self.summary(), self.report)
        self.assertEqual(self.calculate.await_count, 3)

    async def test_deleted_or_foreign_property_cannot_use_cached_revenue(self):
        self.authorize.side_effect = PropertyNotFoundError()
        with self.assertRaises(PropertyNotFoundError):
            await self.summary()
        self.redis.get.assert_not_awaited()
        self.calculate.assert_not_awaited()

    async def test_key_encodes_tenant_property_and_reporting_period(self):
        calls = (
            ("prop-001", "tenant-a", 2024, 3),
            ("prop-001", "tenant-b", 2024, 3),
            ("prop-001", "tenant-a", 2024, 2),
            ("prop-001", "tenant-a", 2024, None),
            ("prop-001", "tenant-a", None, None),
            ("b:c", "a", 2024, 3),
            ("c", "a:b", 2024, 3),
        )
        for arguments in calls:
            await cache.get_revenue_summary(*arguments)
        keys = [call.args[0] for call in self.redis.get.await_args_list]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(key.startswith("revenue:v2:") for key in keys))
        self.assertTrue(all(call.args[1] == 300 for call in self.redis.setex.await_args_list))


class RevenueErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_failure_is_503_not_invented_revenue(self):
        with patch.object(dashboard, "get_revenue_summary", AsyncMock(side_effect=RuntimeError("offline"))):
            with self.assertRaises(HTTPException) as raised:
                await dashboard.get_dashboard_summary("prop-001", 2024, 3, {"tenant_id": "tenant-a"})
        self.assertEqual(raised.exception.status_code, 503)

    async def test_missing_tenant_is_forbidden_before_query(self):
        with patch.object(dashboard, "get_revenue_summary", AsyncMock()) as query:
            for identity in ({}, {"tenant_id": ""}, SimpleNamespace()):
                with self.assertRaises(HTTPException) as raised:
                    await dashboard.get_dashboard_summary("prop-001", 2024, 3, identity)
                self.assertEqual(raised.exception.status_code, 403)
            query.assert_not_awaited()

    async def test_properties_database_failure_is_503(self):
        with patch.object(dashboard, "list_properties", AsyncMock(side_effect=RuntimeError("offline"))):
            with self.assertRaises(HTTPException) as raised:
                await dashboard.get_dashboard_properties({"tenant_id": "tenant-a"})
        self.assertEqual(raised.exception.status_code, 503)


class DatabasePoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_pool_created_once_session_factory_is_synchronous_and_close_resets(self):
        engine = SimpleNamespace(dispose=AsyncMock())
        factory = MagicMock(return_value="session")
        with patch("app.core.database_pool.create_async_engine", return_value=engine) as create:
            with patch("app.core.database_pool.async_sessionmaker", return_value=factory):
                pool = DatabasePool()
                await pool.initialize()
                await pool.initialize()
                create.assert_called_once()
                self.assertEqual(create.call_args.args[0].drivername, "postgresql+asyncpg")
                self.assertNotIn("poolclass", create.call_args.kwargs)
                self.assertEqual(pool.get_session(), "session")
                await pool.close()
                engine.dispose.assert_awaited_once()
                self.assertIsNone(pool.engine)
                self.assertIsNone(pool.session_factory)
                with self.assertRaises(RuntimeError):
                    pool.get_session()

    async def test_close_resets_pool_even_if_dispose_fails(self):
        pool = DatabasePool()
        pool.engine = SimpleNamespace(dispose=AsyncMock(side_effect=RuntimeError("closed")))
        pool.session_factory = MagicMock()
        with self.assertRaises(RuntimeError):
            await pool.close()
        self.assertIsNone(pool.engine)
        self.assertIsNone(pool.session_factory)


class RevenuePeriodTests(unittest.TestCase):
    def test_valid_extreme_years_and_month_rollover(self):
        start, end = revenue_period_bounds(1, 1)
        self.assertEqual((start.year, start.month, end.year, end.month), (1, 1, 1, 2))
        start, end = revenue_period_bounds(9998, 12)
        self.assertEqual((start.year, start.month, end.year, end.month), (9998, 12, 9999, 1))


if __name__ == "__main__":
    unittest.main()

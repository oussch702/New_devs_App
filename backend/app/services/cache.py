import json
import logging
import re
from typing import Any
from urllib.parse import quote

import redis.asyncio as redis

from app.config import settings
from app.core.database_pool import db_pool
from app.services.reservations import (
    calculate_total_revenue,
    require_property,
    revenue_period_bounds,
)

logger = logging.getLogger(__name__)
redis_client = redis.Redis.from_url(
    settings.redis_url, socket_connect_timeout=1, socket_timeout=1
)


def _valid_cached_summary(summary) -> bool:
    """Discard incomplete or malformed cache entries instead of serving them."""
    required = {
        "property_id", "timezone", "year", "month", "reservations_count",
        "total_revenue", "currency", "totals_by_currency",
    }
    if not isinstance(summary, dict) or not required.issubset(summary):
        return False
    groups = summary["totals_by_currency"]
    if not isinstance(groups, list) or not groups:
        return False
    for group in groups:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get("currency"), str)
            or not isinstance(group.get("total_revenue"), str)
            or re.fullmatch(r"-?[0-9]+\.[0-9]{2}", group["total_revenue"]) is None
            or type(group.get("reservations_count")) is not int
            or group["reservations_count"] < 0
        ):
            return False
    if (
        type(summary["reservations_count"]) is not int
        or summary["reservations_count"] != sum(group["reservations_count"] for group in groups)
        or len({group["currency"] for group in groups}) != len(groups)
    ):
        return False
    if len(groups) == 1:
        return (
            summary["currency"] == groups[0]["currency"]
            and summary["total_revenue"] == groups[0]["total_revenue"]
        )
    return summary["currency"] is None and summary["total_revenue"] is None


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Authorize first, then cache the tenant/property/report for five minutes."""
    revenue_period_bounds(year, month)
    async with db_pool.get_session() as session:
        property_data = await require_property(property_id, tenant_id, session)
        # Versioning abandons old keys that omitted tenant or reporting period.
        # Encode parts so separators inside IDs cannot cause a key collision.
        cache_key = "revenue:v2:" + ":".join(
            quote(str(part), safe="")
            for part in (
                tenant_id, property_id, year or "all", month or "all",
                property_data["timezone"],
            )
        )
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                payload = json.loads(cached)
                summary = payload.get("summary")
                if (
                    payload.get("tenant_id") == tenant_id
                    and _valid_cached_summary(summary)
                    and summary.get("property_id") == property_id
                    and summary.get("timezone") == property_data["timezone"]
                    and summary.get("year") == year
                    and summary.get("month") == month
                ):
                    return summary
        except (redis.RedisError, ValueError, TypeError, AttributeError):
            logger.warning("Revenue cache unavailable or invalid; querying the database")

        result = await calculate_total_revenue(
            property_id, tenant_id, year, month, db_session=session
        )
        try:
            await redis_client.setex(
                cache_key, 300, json.dumps({"tenant_id": tenant_id, "summary": result})
            )
        except redis.RedisError:
            logger.warning("Revenue cache write failed; returning database result")
        return result

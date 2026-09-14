from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

from app.core.database_pool import db_pool


class PropertyNotFoundError(LookupError):
    """The requested property does not belong to the authenticated tenant."""


def revenue_period_bounds(year: int | None, month: int | None):
    """Return local calendar boundaries; PostgreSQL applies the property's zone.

    Converting the boundaries in PostgreSQL preserves DST offsets and supports
    the entire accepted year range, including year 1 in positive-offset zones.
    Revenue is recognized in the property-local check-in month, not prorated.
    """
    if month is not None and year is None:
        raise ValueError("A year is required when specifying a month")
    if year is None:
        return None, None
    if not 1 <= year <= 9998 or (month is not None and not 1 <= month <= 12):
        raise ValueError("Invalid reporting period")
    start = datetime(year, month or 1, 1)
    if month is None or month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


async def require_property(property_id: str, tenant_id: str, db_session) -> dict:
    if not tenant_id:
        raise ValueError("Tenant is required")
    result = await db_session.execute(
        text("""
            SELECT id, name, timezone
            FROM properties
            WHERE id = :property_id AND tenant_id = :tenant_id
        """),
        {"property_id": property_id, "tenant_id": tenant_id},
    )
    property_row = result.mappings().first()
    if property_row is None:
        raise PropertyNotFoundError("Property not found")
    return dict(property_row)


async def list_properties(tenant_id: str) -> list[dict]:
    if not tenant_id:
        raise ValueError("Tenant is required")
    async with db_pool.get_session() as session:
        result = await session.execute(
            text("""
                SELECT id, name, timezone
                FROM properties
                WHERE tenant_id = :tenant_id
                ORDER BY id
            """),
            {"tenant_id": tenant_id},
        )
        return [dict(row) for row in result.mappings()]


async def calculate_total_revenue(
    property_id: str,
    tenant_id: str,
    year: int | None = None,
    month: int | None = None,
    *,
    db_session=None,
) -> dict[str, Any]:
    """Sum exact amounts by currency within an authorized property's period."""
    start, end = revenue_period_bounds(year, month)
    if db_session is None:
        async with db_pool.get_session() as session:
            return await calculate_total_revenue(
                property_id, tenant_id, year, month, db_session=session
            )

    property_data = await require_property(property_id, tenant_id, db_session)
    params = {"property_id": property_id, "tenant_id": tenant_id}
    period_filter = ""
    if start is not None:
        # AT TIME ZONE converts each local boundary to a timestamptz instant.
        # Keep check_in_date bare so a tenant/property/date index remains usable.
        period_filter = """
            AND check_in_date >=
                (CAST(:start_date AS TIMESTAMP) AT TIME ZONE :property_timezone)
            AND check_in_date <
                (CAST(:end_date AS TIMESTAMP) AT TIME ZONE :property_timezone)
        """
        params.update(
            start_date=start,
            end_date=end,
            property_timezone=property_data["timezone"],
        )

    result = await db_session.execute(
        text("""
            SELECT COALESCE(currency, 'USD') AS currency,
                   SUM(total_amount) AS total_revenue,
                   COUNT(*) AS reservations_count
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
        """ + period_filter + """
            GROUP BY COALESCE(currency, 'USD')
            ORDER BY currency
        """),
        params,
    )
    totals = [
        {
            "currency": row["currency"],
            "total_revenue": format(
                Decimal(str(row["total_revenue"])).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
                ".2f",
            ),
            "reservations_count": row["reservations_count"],
        }
        for row in result.mappings()
    ]
    if not totals:
        totals = [{"currency": "USD", "total_revenue": "0.00", "reservations_count": 0}]

    single_currency = totals[0] if len(totals) == 1 else None
    return {
        "property_id": property_id,
        "timezone": property_data["timezone"],
        "year": year,
        "month": month,
        "reservations_count": sum(item["reservations_count"] for item in totals),
        "total_revenue": single_currency["total_revenue"] if single_currency else None,
        "currency": single_currency["currency"] if single_currency else None,
        "totals_by_currency": totals,
    }

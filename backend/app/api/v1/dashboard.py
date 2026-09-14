import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import authenticate_request as get_current_user
from app.services.cache import get_revenue_summary
from app.services.reservations import PropertyNotFoundError, list_properties

router = APIRouter()
logger = logging.getLogger(__name__)


def current_tenant(current_user) -> str:
    tenant_id = (
        current_user.get("tenant_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "tenant_id", None)
    )
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise HTTPException(status_code=403, detail="Authenticated tenant is required")
    return tenant_id


@router.get("/dashboard/properties")
async def get_dashboard_properties(
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id = current_tenant(current_user)
    try:
        return {"properties": await list_properties(tenant_id)}
    except Exception:
        logger.error("Property database query failed")
        raise HTTPException(status_code=503, detail="Property data is temporarily unavailable")


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str = Query(..., min_length=1),
    year: int | None = Query(None, ge=1, le=9998),
    month: int | None = Query(None, ge=1, le=12),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id = current_tenant(current_user)
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="A year is required when specifying a month")
    try:
        return await get_revenue_summary(property_id, tenant_id, year, month)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except Exception:
        logger.error("Revenue database query failed")
        raise HTTPException(status_code=503, detail="Revenue data is temporarily unavailable")

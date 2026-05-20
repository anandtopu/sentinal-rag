"""Usage / cost routes (ADR-0039).

Per-tenant cost read-model over ``usage_records`` + ``tenant_budgets`` powering
the console's topbar `cost mtd` chip and dashboard cost tile/sparkline.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sentinelrag_shared.auth import AuthContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_permission
from app.db.session import get_db
from app.schemas.usage import UsageSummary
from app.services.usage_service import UsageService

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary", response_model=UsageSummary)
async def usage_summary(
    # Cost surfaces the same console as metrics; reuse queries:execute
    # (billing:read is unseeded today — see ADR-0039).
    ctx: Annotated[AuthContext, Depends(require_permission("queries:execute"))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UsageSummary:
    """Spend over the active budget period (or calendar month-to-date), budget
    context, and a daily cost series, scoped to the tenant via RLS."""
    return await UsageService(db).summarize(tenant_id=ctx.tenant_id)

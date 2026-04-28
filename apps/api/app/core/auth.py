"""FastAPI bindings for auth: ``require_auth`` + ``require_permission``.

The verifier is constructed once at app startup (lifespan) and stored on
``app.state.jwt_verifier``. The ``require_auth`` dependency:

    1. Extracts the bearer token.
    2. Verifies signature and claims via JWTVerifier.
    3. Loads the user's permission set from the DB.
    4. Builds an AuthContext.
    5. Sets the ``current_tenant_id`` and ``current_user_id`` contextvars
       so downstream sessions auto-bind RLS context.

The same dependency is the ONLY place the runtime tenant context is set.

Local-only dev bypass: when ``settings.environment == 'local'`` AND
``settings.auth_allow_dev_token`` is true, an ``Authorization: Bearer <dev_token_value>``
returns a synthesized AuthContext for the seeded demo tenant + admin user.
The seeded user is provisioned by ``scripts/seed/seed_demo.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sentinelrag_shared.auth import AuthContext, JWTVerifier, JWTVerifierError
from sentinelrag_shared.errors import AuthRequiredError
from sentinelrag_shared.errors.exceptions import AuthInvalidError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories import RoleRepository, UserRepository
from app.db.session import current_tenant_id, current_user_id, get_admin_db


def _get_verifier(request: Request) -> JWTVerifier:
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if verifier is None:
        msg = "JWT verifier not configured."
        raise RuntimeError(msg)
    return verifier


def _bind_request_context(ctx: AuthContext) -> None:
    current_tenant_id.set(ctx.tenant_id)
    current_user_id.set(ctx.user_id)


async def _resolve_dev_auth_context(db: AsyncSession) -> AuthContext:
    """Build an AuthContext for the seeded demo user.

    The seeded user MUST exist in the DB (run ``make seed`` to create it).
    Permissions come from the role assignment in the seed script.
    """
    settings = get_settings()
    user_repo = UserRepository(db)
    user = await user_repo.get(UUID(settings.dev_user_id))
    if user is None:
        msg = (
            "Dev token used but the demo user is not seeded. "
            "Run `make seed` to create it."
        )
        raise AuthInvalidError(msg)
    role_repo = RoleRepository(db)
    permissions = await role_repo.list_user_permission_codes(user.id)
    return AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        permissions=frozenset(permissions),
    )


async def require_auth(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    db: Annotated[AsyncSession, Depends(get_admin_db)] = ...,  # type: ignore[assignment]
) -> AuthContext:
    """Verify the bearer token and yield an AuthContext."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthRequiredError()

    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()

    # ---- Dev-token short-circuit (env-gated, defense-in-depth on TWO flags) ----
    if (
        settings.environment == "local"
        and settings.auth_allow_dev_token
        and token == settings.dev_token_value
    ):
        ctx = await _resolve_dev_auth_context(db)
        _bind_request_context(ctx)
        return ctx

    # ---- Standard JWT path ----
    verifier = _get_verifier(request)
    try:
        claims = await verifier.verify(token)
    except JWTVerifierError as exc:
        raise AuthInvalidError(str(exc)) from exc

    user_repo = UserRepository(db)
    user = await user_repo.get_by_external_id(str(claims.sub))
    if user is None:
        from app.db.models import User  # noqa: PLC0415 — break import cycle
        from app.db.repositories import TenantRepository  # noqa: PLC0415

        tenant = await TenantRepository(db).get_by_id(claims.tenant_id)
        if tenant is None:
            raise AuthInvalidError("Tenant in token does not exist.")
        user = User(
            tenant_id=claims.tenant_id,
            email=claims.email.lower(),
            external_identity_id=str(claims.sub),
            full_name=claims.raw.get("name") or claims.raw.get("preferred_username"),
        )
        db.add(user)
        await db.flush()

    role_repo = RoleRepository(db)
    permissions = await role_repo.list_user_permission_codes(user.id)
    ctx = AuthContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        permissions=frozenset(permissions),
    )
    _bind_request_context(ctx)
    return ctx


def require_permission(code: str) -> Callable[..., Awaitable[AuthContext]]:
    """Dependency factory: ``require_permission('users:write')``."""

    async def _dependency(
        ctx: Annotated[AuthContext, Depends(require_auth)],
    ) -> AuthContext:
        ctx.require_permission(code)
        return ctx

    return _dependency

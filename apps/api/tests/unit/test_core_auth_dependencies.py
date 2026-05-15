"""Unit coverage for FastAPI auth dependency behavior."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app import dependencies
from app.core import auth as auth_module
from app.db.session import current_tenant_id, current_user_id
from sentinelrag_shared.auth import AuthContext
from sentinelrag_shared.errors import (
    AuthRequiredError,
    RBACDeniedError,
    TemporalUnavailableError,
)
from sentinelrag_shared.errors.exceptions import AuthInvalidError


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushes = 0

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()  # type: ignore[attr-defined]
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1


class FakeSettings:
    environment = "local"
    auth_allow_dev_token = True
    dev_token_value = "dev"
    dev_user_id = "00000000-0000-0000-0000-000000000010"


class FakeUserRepo:
    def __init__(self, _db: object, *, user: object | None = None) -> None:
        self.user = user

    async def get(self, _user_id: UUID) -> object | None:
        return self.user

    async def get_by_external_id(self, _external_id: str) -> object | None:
        return self.user


class FakeRoleRepo:
    def __init__(self, _db: object, *, permissions: list[str] | None = None) -> None:
        self.permissions = permissions or ["queries:execute"]

    async def list_user_permission_codes(self, _user_id: UUID) -> list[str]:
        return self.permissions


class FakeVerifier:
    def __init__(self, claims: object) -> None:
        self.claims = claims

    async def verify(self, _token: str) -> object:
        return self.claims


def _request(verifier: object | None = None) -> object:
    state = SimpleNamespace()
    if verifier is not None:
        state.jwt_verifier = verifier
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _state_request(state: object) -> object:
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        email="demo@example.com",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_auth_requires_bearer_token() -> None:
    with pytest.raises(AuthRequiredError):
        await auth_module.require_auth(_request(), authorization=None, db=FakeDb())  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_auth_dev_token_resolves_seeded_user_and_binds_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    monkeypatch.setattr(auth_module, "get_settings", FakeSettings)
    monkeypatch.setattr(auth_module, "UserRepository", lambda db: FakeUserRepo(db, user=user))
    monkeypatch.setattr(
        auth_module,
        "RoleRepository",
        lambda db: FakeRoleRepo(db, permissions=["queries:execute", "llm:cloud_models"]),
    )

    ctx = await auth_module.require_auth(
        _request(),
        authorization="Bearer dev",
        db=FakeDb(),  # type: ignore[arg-type]
    )

    assert ctx.user_id == user.id
    assert ctx.tenant_id == user.tenant_id
    assert ctx.permissions == frozenset({"queries:execute", "llm:cloud_models"})
    assert current_tenant_id.get() == user.tenant_id
    assert current_user_id.get() == user.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_auth_dev_token_requires_seeded_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "get_settings", FakeSettings)
    monkeypatch.setattr(auth_module, "UserRepository", lambda db: FakeUserRepo(db, user=None))

    with pytest.raises(AuthInvalidError, match="demo user is not seeded"):
        await auth_module.require_auth(
            _request(),
            authorization="Bearer dev",
            db=FakeDb(),  # type: ignore[arg-type]
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_auth_jwt_existing_user_loads_database_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user()
    claims = SimpleNamespace(sub="keycloak-sub", tenant_id=user.tenant_id, email=user.email)
    settings = SimpleNamespace(
        environment="dev",
        auth_allow_dev_token=False,
        dev_token_value="dev",
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_module, "UserRepository", lambda db: FakeUserRepo(db, user=user))
    monkeypatch.setattr(
        auth_module,
        "RoleRepository",
        lambda db: FakeRoleRepo(db, permissions=["documents:read"]),
    )

    ctx = await auth_module.require_auth(
        _request(FakeVerifier(claims)),
        authorization="Bearer jwt",
        db=FakeDb(),  # type: ignore[arg-type]
    )

    assert ctx.user_id == user.id
    assert ctx.permissions == frozenset({"documents:read"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_permission_dependency_rejects_missing_permission() -> None:
    dependency = auth_module.require_permission("queries:execute")
    ctx = AuthContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        email="demo@example.com",
        permissions=frozenset(),
    )

    with pytest.raises(RBACDeniedError):
        await dependency(ctx)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_require_permission_dependency_returns_authorized_context() -> None:
    dependency = auth_module.require_permission("queries:execute")
    ctx = AuthContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        email="demo@example.com",
        permissions=frozenset({"queries:execute"}),
    )

    assert await dependency(ctx) is ctx  # type: ignore[arg-type]


@pytest.mark.unit
def test_temporal_dependency_raises_service_unavailable_when_missing() -> None:
    with pytest.raises(TemporalUnavailableError):
        dependencies.get_temporal_client(_state_request(SimpleNamespace()))  # type: ignore[arg-type]

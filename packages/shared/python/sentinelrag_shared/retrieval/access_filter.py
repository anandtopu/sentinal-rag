"""AccessFilter — RBAC predicate builder applied at query time.

Architectural pillar (CLAUDE.md, ADR-0008): RBAC is enforced at retrieval
time, not post-retrieval mask. This module produces a SQL WHERE predicate
that BOTH the BM25 and vector queries apply BEFORE fetching candidates.

Three layers stack here:
    1. **Tenant isolation** — enforced by Postgres RLS via the session-bound
       ``app.current_tenant_id`` setting. The retriever sessions inherit
       this from the request middleware (see ``apps/api/app/db/session.py``).
    2. **Collection scope** — the user passes ``collection_ids`` in the query
       request; we add ``c.collection_id IN (:collection_ids)``.
    3. **Per-collection access policy** — the user must have at least
       read-level access (via role or direct grant) on each collection. We
       enforce this by joining ``collection_access_policies`` to the role
       set the active user holds.

The AccessFilter does NOT issue SQL itself — it returns a predicate fragment
+ parameter dict that the caller injects into its larger query. This keeps
the predicate composable (BM25's CTE and vector search's window can both
apply the same filter without duplicating the join logic).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from sentinelrag_shared.auth import AuthContext


@dataclass(slots=True)
class AccessFilterPredicate:
    """A composable WHERE-predicate fragment + parameter dict.

    The ``sql`` is intended to be appended after a chunk-table alias — it
    references ``chunks.tenant_id``, ``chunks.collection_id`` etc. Callers
    are expected to alias ``document_chunks`` as ``chunks`` (or pass the
    alias via :class:`AccessFilter` constructor).
    """

    sql: str
    params: dict[str, Any]
    cte_sql: str | None = None  # optional: a CTE the caller should prepend


class AccessFilter:
    """Builds an :class:`AccessFilterPredicate` from auth context + scope.

    Parameters
    ----------
    chunks_alias:
        SQL alias for ``document_chunks`` in the surrounding query. Defaults
        to ``"chunks"``. The predicate uses ``{alias}.collection_id`` etc.
    require_access_level:
        Minimum access level required (``read`` < ``write`` < ``admin``).
        For retrieval, ``read`` is the right floor.
    """

    _ACCESS_LEVEL_RANK: ClassVar[dict[str, int]] = {"read": 1, "write": 2, "admin": 3}

    def __init__(
        self,
        *,
        chunks_alias: str = "chunks",
        require_access_level: str = "read",
    ) -> None:
        self.alias = chunks_alias
        self.require_access_level = require_access_level
        if require_access_level not in self._ACCESS_LEVEL_RANK:
            msg = f"Unknown access level: {require_access_level!r}"
            raise ValueError(msg)

    def build(
        self,
        *,
        auth: AuthContext,
        collection_ids: list[UUID] | None,
    ) -> AccessFilterPredicate:
        """Produce a predicate that scopes a chunk query to authorized rows.

        The predicate combines:
            - Explicit collection scope (when ``collection_ids`` is provided).
            - Authorization: only collections where the user holds at least
              ``require_access_level`` access (via role or direct grant) are
              eligible.

        Tenant isolation is NOT included here because Postgres RLS handles it
        already (the session is bound to ``app.current_tenant_id``). Including
        it would be redundant and obscure the WHERE clause.
        """
        params: dict[str, Any] = {
            "auth_user_id": str(auth.user_id),
            "auth_tenant_id": str(auth.tenant_id),
            "min_access_rank": self._ACCESS_LEVEL_RANK[self.require_access_level],
        }

        # Authorized-collections CTE: every collection_id this user can read
        # within their tenant. Combines role-granted and user-granted access.
        cte_sql = """
            WITH authorized_collections AS (
                SELECT DISTINCT c.id AS collection_id
                FROM collections c
                LEFT JOIN collection_access_policies p
                    ON p.collection_id = c.id
                LEFT JOIN user_roles ur
                    ON ur.role_id = p.role_id AND ur.user_id = :auth_user_id
                WHERE c.tenant_id = CAST(:auth_tenant_id AS uuid)
                  AND (
                       -- public-to-tenant collections grant read by default,
                       -- but write/admin still require an explicit policy.
                       (c.visibility = 'tenant' AND :min_access_rank <= 1)
                    OR -- direct user grant
                       (p.user_id = CAST(:auth_user_id AS uuid)
                        AND CASE p.access_level
                              WHEN 'read'  THEN 1
                              WHEN 'write' THEN 2
                              WHEN 'admin' THEN 3
                            END >= :min_access_rank)
                    OR -- role grant where the user holds that role
                       (p.role_id IS NOT NULL
                        AND ur.user_id IS NOT NULL
                        AND CASE p.access_level
                              WHEN 'read'  THEN 1
                              WHEN 'write' THEN 2
                              WHEN 'admin' THEN 3
                            END >= :min_access_rank)
                  )
            )
        """

        # ``document_chunks`` has no collection_id column (collection lives on
        # ``documents``); resolve via a correlated EXISTS rather than denormal-
        # izing the column down. The planner collapses these into a hash
        # semi-join given the FK + index on ``documents(tenant_id, collection_id)``.
        # S608: ``self.alias`` is set by AccessFilter callers from a fixed set
        # of internal aliases (e.g. "chunks"); never user input.
        clauses: list[str] = [
            f"EXISTS (SELECT 1 FROM documents _ac_d "  # noqa: S608
            f"WHERE _ac_d.id = {self.alias}.document_id "
            f"AND _ac_d.collection_id IN "
            f"(SELECT collection_id FROM authorized_collections))"
        ]

        if collection_ids:
            clauses.append(
                f"EXISTS (SELECT 1 FROM documents _rc_d "  # noqa: S608
                f"WHERE _rc_d.id = {self.alias}.document_id "
                f"AND _rc_d.collection_id = ANY(CAST(:requested_collection_ids AS uuid[])))"
            )
            params["requested_collection_ids"] = [str(cid) for cid in collection_ids]

        return AccessFilterPredicate(
            sql=" AND ".join(clauses),
            params=params,
            cte_sql=cte_sql,
        )

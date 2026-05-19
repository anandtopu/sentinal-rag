from __future__ import annotations

import os
from collections.abc import Mapping

DEFAULT_DATABASE_URL = "postgresql+asyncpg://sentinel:sentinel@localhost:15432/sentinelrag"


def get_database_url(environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get("DATABASE_URL", DEFAULT_DATABASE_URL)

"""Base Contract model — the Pydantic config pinning."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Cross-service / cross-process message base.

    Configured to:
        - Forbid extra fields (typo on either side surfaces immediately).
        - Be immutable (``frozen=True``) — Temporal replays inputs; mutation is
          almost always a bug.
        - Serialize datetimes as ISO-8601 with timezone (Pydantic default).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )

"""FeatureFlagClient Protocol + static defaults-driven impl.

The Protocol exposes ``bool_flag`` and ``float_flag``. Both take an
explicit ``default`` so a misconfigured / unreachable flag backend can
never silently flip behavior — the worst case is the documented default.

The Unleash-backed adapter (Phase R-followup) will implement the same
shape; tests and local dev use :class:`StaticFeatureFlags`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class FeatureFlagClient(Protocol):
    """Read a feature flag value with an explicit default fallback."""

    def bool_flag(
        self,
        key: str,
        *,
        default: bool,
        context: Mapping[str, Any] | None = None,
    ) -> bool: ...

    def float_flag(
        self,
        key: str,
        *,
        default: float,
        context: Mapping[str, Any] | None = None,
    ) -> float: ...


class StaticFeatureFlags:
    """In-process flag client driven by an overrides map + defaults.

    Args:
        overrides: ``{flag_key: value}``. Missing keys fall back to the
            ``default`` argument the caller passed to
            ``bool_flag``/``float_flag``.

    The ``context`` argument is accepted for Protocol parity with the
    Unleash adapter but is ignored here.
    """

    def __init__(self, overrides: Mapping[str, Any] | None = None) -> None:
        self._overrides: dict[str, Any] = dict(overrides or {})

    def bool_flag(
        self,
        key: str,
        *,
        default: bool,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        del context
        if key not in self._overrides:
            return default
        return bool(self._overrides[key])

    def float_flag(
        self,
        key: str,
        *,
        default: float,
        context: Mapping[str, Any] | None = None,
    ) -> float:
        del context
        if key not in self._overrides:
            return default
        return float(self._overrides[key])

    def set(self, key: str, value: Any) -> None:
        """Test helper: stage an override after construction."""
        self._overrides[key] = value

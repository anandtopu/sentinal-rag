"""Flag keys + per-feature default snapshots.

Centralizing the keys here prevents drift between the call site and the
default-trio assertion test (see ``test_hallucination_cascade_defaults``).
Adding a new flag = add the constant + extend the defaults dict + extend
the ``resolve_*`` helper if it belongs to a group.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentinelrag_shared.feature_flags.client import FeatureFlagClient


HALLUCINATION_NLI_ENABLED = "hallucination.nli.enabled"
HALLUCINATION_JUDGE_ENABLED = "hallucination.judge.enabled"
HALLUCINATION_JUDGE_SAMPLE_RATE = "hallucination.judge.sample_rate"

# The single source of truth for cascade default semantics. The unit test
# ``test_hallucination_cascade_defaults`` asserts this exact mapping so
# that an accidental edit here is loud.
HALLUCINATION_CASCADE_DEFAULTS: Mapping[str, Any] = {
    HALLUCINATION_NLI_ENABLED: True,
    HALLUCINATION_JUDGE_ENABLED: False,
    HALLUCINATION_JUDGE_SAMPLE_RATE: 0.0,
}


@dataclass(frozen=True, slots=True)
class HallucinationCascadeFlags:
    """Resolved cascade configuration for a single query."""

    nli_enabled: bool
    judge_enabled: bool
    judge_sample_rate: float


def resolve_hallucination_flags(
    client: FeatureFlagClient,
    *,
    context: Mapping[str, Any] | None = None,
) -> HallucinationCascadeFlags:
    """Resolve the three cascade flags in one call, applying defaults.

    Defaults match :data:`HALLUCINATION_CASCADE_DEFAULTS` exactly; the
    Unleash adapter only deviates when the operator explicitly raises a
    flag. ``judge_sample_rate`` is clamped to ``[0.0, 1.0]`` so a typo in
    the flag server can't push it to e.g. 100 (= 10,000% sampling) and
    blow up the LLM bill.
    """
    sample_rate = client.float_flag(
        HALLUCINATION_JUDGE_SAMPLE_RATE,
        default=float(HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_JUDGE_SAMPLE_RATE]),
        context=context,
    )
    sample_rate = max(0.0, min(1.0, sample_rate))
    return HallucinationCascadeFlags(
        nli_enabled=client.bool_flag(
            HALLUCINATION_NLI_ENABLED,
            default=bool(HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_NLI_ENABLED]),
            context=context,
        ),
        judge_enabled=client.bool_flag(
            HALLUCINATION_JUDGE_ENABLED,
            default=bool(HALLUCINATION_CASCADE_DEFAULTS[HALLUCINATION_JUDGE_ENABLED]),
            context=context,
        ),
        judge_sample_rate=sample_rate,
    )

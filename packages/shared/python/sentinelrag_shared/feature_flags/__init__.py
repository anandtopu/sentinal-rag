"""Feature-flag adapter package (ADR-0018).

Defines the :class:`FeatureFlagClient` Protocol the rest of the codebase
codes against, plus a :class:`StaticFeatureFlags` in-process impl driven
by an explicit defaults map. The Unleash-backed adapter is a follow-up
(it lands behind the same Protocol so no caller has to change).

The cascade flag keys are constants so every reader uses the same string
— a typo in one call site can't silently flip a flag.
"""

from sentinelrag_shared.feature_flags.client import (
    FeatureFlagClient,
    StaticFeatureFlags,
)
from sentinelrag_shared.feature_flags.flags import (
    HALLUCINATION_CASCADE_DEFAULTS,
    HALLUCINATION_JUDGE_ENABLED,
    HALLUCINATION_JUDGE_SAMPLE_RATE,
    HALLUCINATION_NLI_ENABLED,
    HallucinationCascadeFlags,
    resolve_hallucination_flags,
)

__all__ = [
    "HALLUCINATION_CASCADE_DEFAULTS",
    "HALLUCINATION_JUDGE_ENABLED",
    "HALLUCINATION_JUDGE_SAMPLE_RATE",
    "HALLUCINATION_NLI_ENABLED",
    "FeatureFlagClient",
    "HallucinationCascadeFlags",
    "StaticFeatureFlags",
    "resolve_hallucination_flags",
]

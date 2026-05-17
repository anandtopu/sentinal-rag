"""Pure helpers used by multiple stages.

Kept private to the ``rag`` package; not exported from ``__init__``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sentinelrag_shared.retrieval import Candidate, RetrievalStage

_CITATION_REF_RE = re.compile(r"\[(\d+)\]")
_MIN_TOKEN_LEN = 3
_CHARS_PER_TOKEN = 4


def approx_token_count(text_blob: str) -> int:
    """Cheap character-based proxy for prompt token count.

    Real tokenization (tiktoken / model-specific) is overkill for a
    budget-gate over-cap. We round up so the estimate biases toward
    deny-then-allow rather than allow-then-overspend.

    Replaced by ``litellm.token_counter`` in R3.S3.
    """
    if not text_blob:
        return 0
    return max(1, (len(text_blob) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def referenced_indices(answer_text: str) -> list[int]:
    return [int(m) for m in _CITATION_REF_RE.findall(answer_text)]


def token_overlap_score(answer: str, context: str) -> float | None:
    """Cheap grounding signal: fraction of answer tokens present in context.

    Returns ``None`` for empty answers. Bigrams would be a stronger signal but
    we keep it cheap. R2 stacks NLI + LLM-judge on top of this layer.
    """
    if not answer.strip():
        return None
    answer_tokens = {
        t.lower() for t in re.findall(r"\w+", answer) if len(t) >= _MIN_TOKEN_LEN
    }
    if not answer_tokens:
        return None
    context_tokens = {
        t.lower() for t in re.findall(r"\w+", context) if len(t) >= _MIN_TOKEN_LEN
    }
    if not context_tokens:
        return 0.0
    return round(len(answer_tokens & context_tokens) / len(answer_tokens), 4)


def restage_candidates(
    candidates: list[Candidate], stage: RetrievalStage
) -> list[Candidate]:
    """Re-emit ``candidates`` carrying a new ``stage`` + re-numbered ``rank``.

    Used by the bm25-only and vector-only modes when synthesizing a
    ``HYBRID_MERGE`` row set for persistence parity.
    """
    return [
        Candidate(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            content=c.content,
            score=c.score,
            rank=rank,
            stage=stage,
            page_number=c.page_number,
            section_title=c.section_title,
            metadata=c.metadata,
        )
        for rank, c in enumerate(candidates, start=1)
    ]


def json_dumps(d: dict[str, Any]) -> str:
    return json.dumps(d, default=str)

"""Pure helpers used by multiple stages.

Kept private to the ``rag`` package; not exported from ``__init__``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import litellm
import structlog
from sentinelrag_shared.retrieval import Candidate, RetrievalStage

_CITATION_REF_RE = re.compile(r"\[(\d+)\]")
_MIN_TOKEN_LEN = 3
_CHARS_PER_TOKEN = 4

_log = structlog.get_logger(__name__)


def token_count(*, model: str, text: str) -> int:
    """Real per-model token count via LiteLLM's tokenizer registry.

    Falls back to a character-based estimate when LiteLLM doesn't know
    the model (e.g. an exotic Ollama tag). Emits a one-shot structured
    warning per process per unknown model so an operator sees the
    fallback fire without flooding logs.

    R3.S3: replaces the previous ``approx_token_count(text)`` proxy in
    the budget gate. Char-based fallback is rounded up — the gate
    prefers deny-then-allow over allow-then-overspend.
    """
    if not text:
        return 0
    try:
        return int(litellm.token_counter(model=model, text=text))
    except Exception as exc:  # litellm raises ValueError/TypeError for unknown models
        _warn_once_unknown_model(model=model, exc=exc)
        return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


# Set of (model,) values we've already warned about — one warning per
# process per unknown model is enough; the operator response is the
# same regardless of how many times the fallback fires.
_WARNED_UNKNOWN_MODELS: set[str] = set()


def _warn_once_unknown_model(*, model: str, exc: Exception) -> None:
    if model in _WARNED_UNKNOWN_MODELS:
        return
    _WARNED_UNKNOWN_MODELS.add(model)
    _log.warning(
        "litellm.token_counter unknown model; falling back to char/4 estimate",
        model=model,
        exception_type=type(exc).__name__,
        exception=str(exc)[:200],
    )


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


def fill_prompt(template: str, *, query: str, context: str) -> str:
    """Substitute ``{query}`` + ``{context}`` placeholders without ``.format()``.

    R3.S7: ``str.format`` walks the entire template looking for
    ``{anything}`` and explodes if the context (or query) contains
    literal braces — common when the retrieved passages include JSON,
    LaTeX, code, or arbitrary user-pasted text. This helper does a
    deliberate placeholder replace so:

    * ``{query}`` and ``{context}`` get substituted exactly once each;
    * every other ``{...}`` in the *template itself* is preserved
      verbatim (prompt-author error — flag in review, not at runtime);
    * any ``{`` or ``}`` in the *substituted values* is left untouched.

    Order matters: substitute ``{context}`` first because the
    retrieved passages tend to be much larger than the query, so we
    avoid scanning them twice.
    """
    return template.replace("{context}", context).replace("{query}", query)

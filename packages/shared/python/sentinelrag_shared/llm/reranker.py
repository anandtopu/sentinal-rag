from __future__ import annotations

from typing import Any


class RerankerError(Exception):
    pass


class Reranker:
    def __init__(self, model_name: str, max_length: int = 512) -> None:
        self.model_name = model_name
        self.max_length = max_length

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        try:
            from FlagEmbedding import FlagReranker as _FlagReranker  # type: ignore[import-not-found]
        except ImportError:
            _FlagReranker = None

        if _FlagReranker is not None:
            try:
                _flag_model = _FlagReranker(self.model_name)
                _scores = _flag_model.compute_score(
                    pairs,
                    normalize=True,
                )
                return list(_scores)
            except Exception:
                pass

        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RerankerError(
                "Neither FlagEmbedding nor sentence-transformers is installed."
            ) from exc

        try:
            _bge_model = CrossEncoder(self.model_name, max_length=self.max_length)
            return list(
                _bge_model.predict(
                    pairs,
                    convert_to_numpy=True,
                )
            )
        except Exception as exc:
            raise RerankerError(
                f"Could not load reranker model {self.model_name!r}: {exc}"
            ) from exc

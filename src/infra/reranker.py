import asyncio
import math
from collections.abc import Sequence

from domain.errors import RerankError


class CrossEncoderReranker:
    """Local cross-encoder (sentence-transformers). Deterministic: eval mode, no sampling, fixed batch order.

    Scores are sentence-transformers' default output for a one-label re-ranker: sigmoid(logit), a relevance
    value in (0, 1). Compare them within one query only; they are not on the same scale as fused RRF scores.
    """

    def __init__(self, model_name: str, device: str = "cpu", max_length: int = 512) -> None:
        from sentence_transformers import CrossEncoder

        self._name = model_name
        try:
            self._model = CrossEncoder(model_name, device=device, max_length=max_length, local_files_only=True)
        except Exception:
            self._model = CrossEncoder(model_name, device=device, max_length=max_length)

    @property
    def model_name(self) -> str:
        return self._name

    def _predict(self, query: str, passages: list[str]) -> list[float]:
        return [float(s) for s in self._model.predict([(query, p) for p in passages], batch_size=32,
                                                      convert_to_numpy=True, show_progress_bar=False)]

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        try:
            scores = await asyncio.to_thread(self._predict, query, list(passages))
        except Exception as e:
            raise RerankError("cross-encoder failed", stage="rerank", model=self._name, batch=len(passages),
                              error=type(e).__name__) from e
        if len(scores) != len(passages) or not all(math.isfinite(s) for s in scores):
            raise RerankError("cross-encoder returned malformed scores", stage="rerank", model=self._name,
                              batch=len(passages))
        return scores

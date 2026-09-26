import asyncio
from collections.abc import Sequence

from domain.errors import EmbeddingError


class SentenceTransformerEmbedder:
    """Local embeddings. Vectors are L2-normalised so cosine distance in pgvector equals 1 - dot."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)
        self._dimension = self._model.get_embedding_dimension()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_tokens(self) -> int:
        return self._model.max_seq_length

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer(text, add_special_tokens=True)["input_ids"])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, batch_size=64, normalize_embeddings=True, convert_to_numpy=True).tolist()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await asyncio.to_thread(self._encode, list(texts))
        except Exception as e:
            raise EmbeddingError("embedding failed", stage="embed", batch=len(texts), error=type(e).__name__) from e
        if len(vectors) != len(texts) or any(len(v) != self._dimension for v in vectors):
            raise EmbeddingError("embedder returned malformed output", stage="embed", batch=len(texts))
        return vectors

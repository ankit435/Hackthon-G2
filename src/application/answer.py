"""Separate, non-graded answer generation over deterministic hybrid-search results."""
from __future__ import annotations

from domain.errors import InvalidInputError
from domain.models import AnswerResult, SearchResultItem
from domain.ports import AnswerGenerator

MAX_SOURCES = 8
MAX_CONTEXT_CHARS = 12_000


def _context(results: list[SearchResultItem]) -> str:
    """Numbered, bounded evidence. The LLM never chooses authoritative citation metadata."""
    remaining, blocks = MAX_CONTEXT_CHARS, []
    for number, result in enumerate(results[:MAX_SOURCES], start=1):
        text = result.text[:remaining]
        if not text:
            break
        blocks.append(
            f"[{number}] file={result.file_name}; speaker={result.speaker}; "
            f"time={result.start_time:.2f}-{result.end_time:.2f}s; language={result.language}\n{text}"
        )
        remaining -= len(text)
    return "\n\n".join(blocks)


class AnswerService:
    """Adds synthesis after search; it never changes SearchService or the evaluated retrieval path."""

    def __init__(self, search, generator: AnswerGenerator) -> None:
        self._search, self._generator = search, generator

    async def answer(self, query: str, top_k: int = 5) -> AnswerResult:
        if not isinstance(query, str) or not query.strip():
            raise InvalidInputError("query must not be empty", stage="answer")
        results = await self._search.search(query, top_k)
        sources = tuple(results[:MAX_SOURCES])
        if not sources:
            return AnswerResult("I couldn't find relevant audio segments for that question.", ())
        generated = await self._generator.answer(query.strip(), _context(list(sources)))
        return AnswerResult(generated, sources)

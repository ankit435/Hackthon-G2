"""The optional NVIDIA answer feature must remain downstream of deterministic retrieval."""
import asyncio
from uuid import uuid4

import pytest

from application.answer import AnswerService
from domain.errors import InvalidInputError
from domain.models import SearchResultItem


class Search:
    def __init__(self, results):
        self.results, self.calls = results, []

    async def search(self, query, top_k):
        self.calls.append((query, top_k))
        return self.results


class Generator:
    def __init__(self):
        self.calls = []

    async def answer(self, query, context):
        self.calls.append((query, context))
        return "Grounded answer [1]."


def hit(text="A token bucket controls request rate."):
    return SearchResultItem(uuid4(), uuid4(), "audio.wav", "/audio.wav", "SPEAKER_00", 2.0, 6.0,
                            text, "en", 0.1)


def test_answers_only_after_existing_search_and_returns_its_sources():
    search, generator = Search([hit()]), Generator()
    result = asyncio.run(AnswerService(search, generator).answer("What controls request rate?", 3))
    assert search.calls == [("What controls request rate?", 3)]
    assert result.answer == "Grounded answer [1]." and result.sources[0].file_name == "audio.wav"
    assert "[1] file=audio.wav; speaker=SPEAKER_00; time=2.00-6.00s" in generator.calls[0][1]


def test_empty_retrieval_does_not_call_nvidia():
    search, generator = Search([]), Generator()
    result = asyncio.run(AnswerService(search, generator).answer("Anything?"))
    assert result.sources == () and generator.calls == []


@pytest.mark.parametrize("query", ["", "  ", None])
def test_blank_query_is_rejected_before_search(query):
    with pytest.raises(InvalidInputError):
        asyncio.run(AnswerService(Search([]), Generator()).answer(query))

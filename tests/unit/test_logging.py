"""JSON logging stays machine-readable and preserves structured event fields."""
import json
import logging

from api.container import JsonFormatter


def test_json_formatter_emits_one_object_with_extra_fields():
    record = logging.LogRecord("audio.search", logging.INFO, __file__, 1, "search complete", (), None)
    record.event = "search.response"
    record.query_hash = "abc123"
    record.duration_ms = 12.5

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "audio.search"
    assert payload["msg"] == "search complete"
    assert payload["event"] == "search.response"
    assert payload["query_hash"] == "abc123"
    assert payload["duration_ms"] == 12.5

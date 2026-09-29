import logging

import pytest

from api.settings import Settings, load_settings
from domain.errors import ConfigurationError
from domain.models import Branch

DB = "postgresql://u:p@localhost:5432/x"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Ignore the developer's real .env and environment so each test sees only what it sets."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in ("HF_TOKEN", *(f"AUDIO_SEARCH_{f.upper()}" for f in Settings.model_fields)):
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_the_documented_baseline():
    s = load_settings(database_url=DB)
    assert s.rrf_k == 60
    assert s.fusion_weights == {Branch.KEYWORD: 1.0, Branch.SEMANTIC: 1.0}
    assert (s.split_soft_min_seconds, s.split_cap_seconds) == (20.0, 45.0)
    assert s.hnsw_ef_search == 40
    assert s.candidate_depth_multiplier == 5  # decided in Task 5


def test_reads_prefixed_env_and_unprefixed_hf_token(monkeypatch):
    monkeypatch.setenv("AUDIO_SEARCH_DATABASE_URL", DB)
    monkeypatch.setenv("AUDIO_SEARCH_RRF_K", "30")
    monkeypatch.setenv("AUDIO_SEARCH_FUSION_WEIGHT_SEMANTIC", "0.5")
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    s = load_settings()
    assert (s.database_url, s.rrf_k, s.fusion_weight_semantic, s.hf_token) == (DB, 30, 0.5, "hf_test")


def test_unprefixed_app_vars_and_unrelated_keys_are_ignored(monkeypatch):
    monkeypatch.setenv("RRF_K", "5")
    monkeypatch.setenv("AUDIO_SEARCH_ANSWER_MODEL", "some-llm")
    s = load_settings(database_url=DB)
    assert s.rrf_k == 60 and s.answer_model == "some-llm"


def test_nvidia_key_uses_only_nvidia_env_names(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi_test")
    assert load_settings(database_url=DB).nvidia_api_key == "nvapi_test"


def test_missing_database_url_is_a_configuration_error():
    with pytest.raises(ConfigurationError, match="database_url"):
        load_settings()


@pytest.mark.parametrize("value", [-0.1, "abc", float("nan"), float("inf")])
def test_invalid_fusion_weight_is_rejected(value):
    with pytest.raises(ConfigurationError, match="fusion_weight_keyword"):
        load_settings(database_url=DB, fusion_weight_keyword=value)


def test_zero_weight_is_legal_but_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="api.settings"):
        s = load_settings(database_url=DB, fusion_weight_semantic=0.0)
    assert s.fusion_weights[Branch.SEMANTIC] == 0.0
    assert any("branch disabled" in r.message and r.branch == "semantic" for r in caplog.records)


@pytest.mark.parametrize("field,value", [("rrf_k", 0), ("hnsw_ef_search", 0), ("candidate_depth_multiplier", 0)])
def test_non_positive_integers_are_rejected(field, value):
    with pytest.raises(ConfigurationError, match=field):
        load_settings(database_url=DB, **{field: value})


def test_blank_candidate_depth_multiplier_uses_the_default(monkeypatch):
    monkeypatch.setenv("AUDIO_SEARCH_CANDIDATE_DEPTH_MULTIPLIER", "")
    assert load_settings(database_url=DB).candidate_depth_multiplier == 5


def test_split_window_must_be_ordered():
    with pytest.raises(ConfigurationError, match="must be <"):
        load_settings(database_url=DB, split_soft_min_seconds=45, split_cap_seconds=45)


def test_unknown_log_level_is_rejected():
    with pytest.raises(ConfigurationError, match="log_level"):
        load_settings(database_url=DB, log_level="LOUD")


@pytest.mark.parametrize("value,expected", [("", None), ("  ", None), ("es", "es"), ("ZH", "zh")])
def test_transcription_language_blank_means_autodetect(monkeypatch, value, expected):
    monkeypatch.setenv("AUDIO_SEARCH_TRANSCRIPTION_LANGUAGE", value)
    assert load_settings(database_url=DB).transcription_language == expected


def test_unknown_transcription_language_is_rejected():
    with pytest.raises(ConfigurationError, match="transcription_language"):
        load_settings(database_url=DB, transcription_language="klingon")


def test_transcription_language_defaults_to_autodetect():
    assert load_settings(database_url=DB).transcription_language is None


def test_embedding_defaults_are_bge_m3_on_cpu():
    s = load_settings(database_url=DB)
    assert (s.embedding_model, s.embedding_device) == ("BAAI/bge-m3", "cpu")


@pytest.mark.parametrize("device", ["cpu", "mps", "cuda"])
def test_embedding_device_accepts_known_values(device):
    assert load_settings(database_url=DB, embedding_device=device).embedding_device == device


def test_unknown_embedding_device_is_rejected():
    with pytest.raises(ConfigurationError, match="embedding_device"):
        load_settings(database_url=DB, embedding_device="tpu")


def test_embedding_model_is_overridable(monkeypatch):
    monkeypatch.setenv("AUDIO_SEARCH_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    assert load_settings(database_url=DB).embedding_model == "sentence-transformers/all-MiniLM-L6-v2"


def test_reranker_is_off_by_default_and_blank_means_off(monkeypatch):
    s = load_settings(database_url=DB)
    assert (s.reranker_model, s.reranker_device, s.rerank_depth) == (None, "cpu", 30)
    monkeypatch.setenv("AUDIO_SEARCH_RERANKER_MODEL", "  ")
    assert load_settings(database_url=DB).reranker_model is None
    monkeypatch.setenv("AUDIO_SEARCH_RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
    monkeypatch.setenv("AUDIO_SEARCH_RERANK_DEPTH", "40")
    s = load_settings(database_url=DB)
    assert (s.reranker_model, s.rerank_depth) == ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", 40)


@pytest.mark.parametrize("depth", ["0", "101", "x"])
def test_invalid_rerank_depth_is_rejected(monkeypatch, depth):
    monkeypatch.setenv("AUDIO_SEARCH_RERANK_DEPTH", depth)
    with pytest.raises(ConfigurationError, match="rerank_depth"):
        load_settings(database_url=DB)


def test_context_embedding_defaults_on_and_can_be_disabled(monkeypatch):
    assert load_settings(database_url=DB).context_embedding is True
    monkeypatch.setenv("AUDIO_SEARCH_CONTEXT_EMBEDDING", "false")
    assert load_settings(database_url=DB).context_embedding is False

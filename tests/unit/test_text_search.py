import logging

import pytest

from infra import text_search
from infra.text_search import FALLBACK_CONFIG, cjk_bigrams, config_for

SERVER = {"english", "spanish", "hindi", "simple", "german"}


@pytest.mark.parametrize("text", [
    "We should do the whole check inside a single Lua script.",
    "Deberíamos hacer toda la comprobación dentro de un único script.",
    "हमें पूरी जाँच एक ही स्क्रिप्ट के अंदर करनी चाहिए।",
    "", "   ", "429 Too Many Requests",
])
def test_identity_on_non_cjk_text(text):
    assert cjk_bigrams(text) == text


def test_han_run_becomes_overlapping_bigrams():
    assert cjk_bigrams("限流器很重要") == "限流 流器 器很 很重 重要"


def test_single_character_run_is_kept():
    assert cjk_bigrams("用 Redis") == "用 Redis"


def test_mixed_script_keeps_latin_and_bigrams_cjk():
    assert cjk_bigrams("在Redis里用Lua脚本") == "在 Redis 里用 Lua 脚本"  # "里用" is a 2-char run: one bigram
    assert cjk_bigrams("我们用 Lua 脚本。") == "我们 们用 Lua 脚本 。"  # "我们用" is one 3-char run


def test_kana_and_hangul_are_bigrammed():
    assert cjk_bigrams("カタカナ") == "カタ タカ カナ"
    assert cjk_bigrams("한국어") == "한국 국어"


def test_query_bigrams_are_a_subset_of_indexed_bigrams():
    # the property keyword search relies on: a sub-phrase's bigrams all occur in the longer text
    assert set(cjk_bigrams("限流器").split()) <= set(cjk_bigrams("限流器很重要").split())


def test_config_for_mapped_language():
    assert config_for("es", SERVER) == "spanish" and config_for("en", SERVER) == "english"


def test_cjk_languages_use_simple():
    assert config_for("zh", SERVER) == "simple"


@pytest.mark.parametrize("language,reason", [("sw", "unmapped language"), ("fr", "config missing on server")])
def test_fallback_is_simple_warned_and_counted(language, reason, caplog):
    before = text_search.fallback_counts[language]
    with caplog.at_level(logging.WARNING, logger="infra.text_search"):
        assert config_for(language, SERVER) == FALLBACK_CONFIG == "simple"
    assert text_search.fallback_counts[language] == before + 1
    [r] = [r for r in caplog.records if getattr(r, "event", "") == "search.config.fallback"]
    assert (r.language, r.reason) == (language, reason)


def test_fallback_is_never_english():
    assert config_for("xx", SERVER) != "english"

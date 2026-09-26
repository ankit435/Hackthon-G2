"""Per-language keyword search configuration (PLAN.md §7B, M5). Infra only: never stem in application code.

Each chunk stores `search_config` (a Postgres text search configuration chosen from its language)
and `search_text` (its text after CJK bigramming). The generated tsvector is
to_tsvector(search_config, search_text). The query side must run the SAME bigram function and
parse with the SAME config, or matches vanish silently.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

# ISO 639-1 → Postgres Snowball configuration. zh/ja/ko have no stemmer: they use 'simple' over bigrams.
ISO_TO_CONFIG: dict[str, str] = {
    "ar": "arabic", "ca": "catalan", "da": "danish", "de": "german", "el": "greek", "en": "english",
    "es": "spanish", "eu": "basque", "fi": "finnish", "fr": "french", "ga": "irish", "hi": "hindi",
    "hu": "hungarian", "hy": "armenian", "id": "indonesian", "it": "italian", "lt": "lithuanian",
    "ne": "nepali", "nl": "dutch", "no": "norwegian", "pt": "portuguese", "ro": "romanian",
    "ru": "russian", "sr": "serbian", "sv": "swedish", "ta": "tamil", "tr": "turkish", "yi": "yiddish",
    "zh": "simple", "ja": "simple", "ko": "simple",
}
FALLBACK_CONFIG = "simple"  # never 'english': English stemming would mangle other languages silently

fallback_counts: Counter[str] = Counter()  # language -> times it fell back; reported, never hidden


def config_for(language: str, available: set[str]) -> str:
    """The server's config for `language`, else 'simple' with a WARNING and a count (never a silent default)."""
    mapped = ISO_TO_CONFIG.get(language)
    if mapped is not None and mapped in available:
        return mapped
    fallback_counts[language] += 1
    log.warning("no text search config for language; using simple (no stemming)",
                extra={"event": "search.config.fallback", "language": language, "mapped": mapped,
                       "reason": "unmapped language" if mapped is None else "config missing on server"})
    return FALLBACK_CONFIG


# Han (CJK Unified + Extension A), Hiragana, Katakana, Hangul syllables.
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿぀-ゟ゠-ヿ가-힯]+")


def _bigrams(run: str) -> str:
    return run if len(run) == 1 else " ".join(run[i:i + 2] for i in range(len(run) - 1))


def cjk_bigrams(text: str) -> str:
    """Rewrite each CJK run as space-separated overlapping bigrams; leave everything else untouched.

    Postgres has no word segmenter for Chinese/Japanese/Korean, and 'simple' would index a whole
    run as one token, so no sub-phrase could ever match. Bigrams make "限流器" match inside
    "限流器很重要" (both sides share 限流 and 流器). Identity on text containing no CJK characters,
    so English and other languages are byte-for-byte unchanged. A 1-character run stays as is.
    """
    if not _CJK_RUN.search(text):
        return text
    return re.sub(r"\s+", " ", _CJK_RUN.sub(lambda m: f" {_bigrams(m.group(0))} ", text)).strip()

"""Text analyzers: turn text into search tokens, per language (en, es, ja)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer
from unidecode import unidecode

from rootsight.data.german import to_english_words

WORD = re.compile(r"\w+")

STOPWORDS = {
    "en": frozenset(
        [
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "by",
            "for",
            "from",
            "in",
            "is",
            "it",
            "of",
            "on",
            "or",
            "the",
            "to",
            "with",
        ]
    ),
    "es": frozenset(
        ["a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "o", "para", "por", "un", "una", "y"]
    ),
}
_STEMMERS = {lang: snowballstemmer.stemmer(name) for lang, name in (("en", "english"), ("es", "spanish"))}


@lru_cache(maxsize=200_000)
def _stem(lang: str, word: str) -> str:
    return _STEMMERS[lang].stemWord(word)


def _bigrams(text: str) -> list[str]:
    """Character bigrams of each word-like chunk (a single character stays as it is)."""
    tokens: list[str] = []
    for chunk in WORD.findall(unicodedata.normalize("NFKC", text).lower()):
        tokens.extend([chunk] if len(chunk) == 1 else (chunk[i : i + 2] for i in range(len(chunk) - 1)))
    return tokens


def analyze(text: str, lang: str) -> list[str]:
    """Tokenise `text` for `lang`: en stems, es strips accents then stems, ja uses bigrams, de maps to English first."""
    if lang == "ja":
        return _bigrams(text)
    if lang == "de":
        return [_stem("en", w) for w in to_english_words(text) if w not in STOPWORDS["en"]]
    lowered = text.lower()
    if lang == "es":
        lowered = unidecode(lowered)
    return [_stem(lang, w) for w in WORD.findall(lowered) if w not in STOPWORDS[lang]]

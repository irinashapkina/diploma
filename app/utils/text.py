from __future__ import annotations

import re
from functools import lru_cache

from langdetect import DetectorFactory, LangDetectException, detect
from nltk.stem.snowball import RussianStemmer
from nltk.stem.snowball import SnowballStemmer

DetectorFactory.seed = 0

_re_ws = re.compile(r"\s+")
_re_line_hyphen = re.compile(r"(\w)-\n(\w)")
_re_newlines = re.compile(r"\n{2,}")
_re_noise = re.compile(r"[^\S\r\n]+")
_re_token = re.compile(r"[A-Za-zА-Яа-я0-9_#\+\-]{2,}")


@lru_cache(maxsize=2)
def get_stemmers() -> tuple[RussianStemmer, SnowballStemmer]:
    return RussianStemmer(), SnowballStemmer("english")


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    text = _re_line_hyphen.sub(r"\1\2", text)
    text = text.replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    text = _re_newlines.sub("\n\n", text)
    text = _re_noise.sub(" ", text)
    return text.strip()


def normalize_text(text: str) -> str:
    text = clean_ocr_text(text).lower()
    text = text.replace("ё", "е")
    text = _re_ws.sub(" ", text)
    return text.strip()


def detect_language(text: str) -> str:
    txt = normalize_text(text)
    if not txt:
        return "unknown"
    ru_count = len(re.findall(r"[А-Яа-я]", txt))
    en_count = len(re.findall(r"[A-Za-z]", txt))
    if ru_count > 0 and en_count > 0:
        return "mixed"
    try:
        guessed = detect(txt)
    except LangDetectException:
        return "unknown"
    if guessed == "ru":
        return "ru"
    if guessed == "en":
        return "en"
    if ru_count and en_count:
        return "mixed"
    return "unknown"


def tokenize_mixed(text: str) -> list[str]:
    return _re_token.findall(normalize_text(text))


def normalize_for_retrieval(text: str) -> str:
    ru_stemmer, en_stemmer = get_stemmers()
    tokens = tokenize_mixed(text)
    normalized: list[str] = []
    for tok in tokens:
        if re.search(r"[А-Яа-я]", tok):
            normalized.append(ru_stemmer.stem(tok))
        elif re.search(r"[A-Za-z]", tok):
            normalized.append(en_stemmer.stem(tok))
        else:
            normalized.append(tok)
    return " ".join(normalized)


def extract_keywords(text: str, max_terms: int = 8) -> list[str]:
    tokens = tokenize_mixed(text)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_terms:
            break
    return out


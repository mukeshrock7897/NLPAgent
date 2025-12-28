from __future__ import annotations

import re
import string
from typing import List

_PUNCT_TABLE = str.maketrans({c: " " for c in string.punctuation})

def clean_text(text: str) -> str:
    if text is None:
        return ""
    t = text.lower().translate(_PUNCT_TABLE)
    t = re.sub(r"\s+", " ", t).strip()
    return t

_FINANCIAL_DISCLAIMER_PATTERNS = [
    r"forward[- ]looking statements?.{0,4000}",
    r"safe harbor.{0,4000}",
    r"not (an? )?offer.{0,2000}",
    r"no representation or warranty.{0,2000}",
    r"risk factors.{0,3000}",
]

def clean_financial_text(text: str) -> str:
    if text is None:
        return ""
    t = re.sub(r"\r\n?", "\n", text)

    # Remove repeated header/footer-like lines (simple heuristic)
    lines = [ln.strip() for ln in t.splitlines()]
    freq = {}
    for ln in lines:
        if 10 <= len(ln) <= 120:
            freq[ln] = freq.get(ln, 0) + 1
    repeated = {ln for ln, c in freq.items() if c >= 6}

    filtered = [ln for ln in lines if ln not in repeated]
    t = "\n".join(filtered)

    # Remove disclaimer spans
    for pat in _FINANCIAL_DISCLAIMER_PATTERNS:
        t = re.sub(pat, " ", t, flags=re.IGNORECASE | re.DOTALL)

    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()

def tokenize(text: str, mode: str = "regex") -> List[str]:
    if not text:
        return []
    mode = (mode or "regex").lower().strip()
    if mode == "spacy":
        try:
            import spacy  # type: ignore
            try:
                nlp = spacy.load("en_core_web_sm")
            except Exception:
                return re.findall(r"[A-Za-z0-9_]+", text.lower())
            doc = nlp(text)
            return [t.text.lower() for t in doc if not t.is_space]
        except Exception:
            return re.findall(r"[A-Za-z0-9_]+", text.lower())
    return re.findall(r"[A-Za-z0-9_]+", text.lower())

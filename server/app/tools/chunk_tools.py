from __future__ import annotations

import re
from typing import List

def _split_paragraphs(text: str) -> List[str]:
    return [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]

def _split_sentences(text: str) -> List[str]:
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text.strip())
    return [s.strip() for s in sents if s.strip()]

def _window_join(units: List[str], max_chars: int, overlap: int) -> List[str]:
    chunks = []
    cur = ""
    for u in units:
        if not cur:
            cur = u
            continue
        if len(cur) + 1 + len(u) <= max_chars:
            cur = f"{cur} {u}"
        else:
            chunks.append(cur.strip())
            if overlap > 0:
                cur = (cur[-overlap:] + " " + u).strip()
            else:
                cur = u
    if cur.strip():
        chunks.append(cur.strip())
    return chunks

def semantic_chunker(text: str, strategy: str = "paragraph", max_chars: int = 1200, overlap: int = 120) -> List[str]:
    if not text:
        return []
    strategy = (strategy or "paragraph").lower().strip()
    if strategy == "paragraph":
        return _window_join(_split_paragraphs(text), max_chars=max_chars, overlap=overlap)
    if strategy == "sentence":
        return _window_join(_split_sentences(text), max_chars=max_chars, overlap=overlap)
    if strategy == "recursive":
        paras = _split_paragraphs(text)
        units: List[str] = []
        for p in paras:
            if len(p) > max_chars:
                units.extend(_split_sentences(p))
            else:
                units.append(p)
        return _window_join(units, max_chars=max_chars, overlap=overlap)
    raise ValueError(f"Unknown strategy: {strategy}")

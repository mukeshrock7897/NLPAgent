from __future__ import annotations

from typing import Dict, List
from .vector_tools import vector_query

def evaluate_retrieval(query: str, index_name: str, expected_terms: List[str], top_k: int = 5) -> Dict[str, object]:
    expected = [t.lower().strip() for t in expected_terms if t.strip()]
    out = vector_query(query=query, index_name=index_name, top_k=top_k)
    results = out.get("results", [])
    corpus = "\n".join([r.get("text","") for r in results]).lower()
    hits = {t: (t in corpus) for t in expected}
    hit_rate = (sum(1 for v in hits.values() if v) / len(hits)) if hits else 0.0
    preview = [{"id": r.get("id"), "distance": r.get("distance"), "metadata": r.get("metadata")} for r in results]
    return {
        "index": index_name,
        "top_k": top_k,
        "hits": hits,
        "term_hit_rate": float(hit_rate),
        "any_hit": bool(any(hits.values())) if hits else False,
        "results_preview": preview,
    }

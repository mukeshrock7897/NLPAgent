from __future__ import annotations

import os
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

def embed_texts(texts: List[str], model_name: Optional[str] = None) -> List[List[float]]:
    if not texts:
        return []
    model_name = model_name or os.getenv("EMBED_MODEL") or "sentence-transformers/all-MiniLM-L6-v2"
    from sentence_transformers import SentenceTransformer  # type: ignore
    model = SentenceTransformer(model_name)
    vecs = model.encode(texts, normalize_embeddings=True).tolist()
    return [[float(x) for x in v] for v in vecs]

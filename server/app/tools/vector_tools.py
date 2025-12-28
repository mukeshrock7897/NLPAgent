from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

def _client():
    import chromadb  # type: ignore
    chroma_dir = os.getenv("CHROMA_DIR", ".chroma")
    return chromadb.PersistentClient(path=chroma_dir)

def vector_upsert(
    chunks: List[str],
    index_name: str = "default",
    metadatas: Optional[List[Dict[str, Any]]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    if not chunks:
        return {"index": index_name, "upserted": 0}

    client = _client()
    collection = client.get_or_create_collection(name=index_name)

    start = int(collection.count())
    ids = [f"{index_name}-{start+i}" for i in range(len(chunks))]
    metadatas = metadatas or [{"source": "unknown", "chunk": i} for i in range(len(chunks))]
    if len(metadatas) != len(chunks):
        raise ValueError("metadatas length must match chunks length")

    if embeddings is not None:
        if len(embeddings) != len(chunks):
            raise ValueError("embeddings length must match chunks length")
        vectors = embeddings
    else:
        from .embed_tools import embed_texts
        vectors = embed_texts(chunks, model_name=os.getenv("EMBED_MODEL") or None)

    collection.add(ids=ids, documents=chunks, metadatas=metadatas, embeddings=vectors)
    return {"index": index_name, "upserted": len(chunks), "count": int(collection.count())}

def vector_query(query: str, index_name: str = "default", top_k: int = 5) -> Dict[str, Any]:
    if not query:
        return {"index": index_name, "results": []}
    client = _client()
    collection = client.get_or_create_collection(name=index_name)
    if collection.count() == 0:
        return {"index": index_name, "results": []}

    from .embed_tools import embed_texts
    qvec = embed_texts([query], model_name=os.getenv("EMBED_MODEL") or None)[0]
    out = collection.query(query_embeddings=[qvec], n_results=int(top_k))

    docs = out.get("documents", [[]])[0]
    metas = out.get("metadatas", [[]])[0]
    dists = out.get("distances", [[]])[0]
    ids = out.get("ids", [[]])[0]

    results = []
    for i in range(len(docs)):
        results.append({
            "id": ids[i] if i < len(ids) else None,
            "text": docs[i],
            "metadata": metas[i] if i < len(metas) else {},
            "distance": float(dists[i]) if i < len(dists) else None,
        })
    return {"index": index_name, "results": results}

def vector_stats(index_name: str = "default") -> Dict[str, Any]:
    client = _client()
    collection = client.get_or_create_collection(name=index_name)
    return {"index": index_name, "count": int(collection.count())}

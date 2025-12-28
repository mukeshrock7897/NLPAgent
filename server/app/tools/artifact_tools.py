from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..store.artifact_store import put_text, get_text, preview_text, put_chunks, get_chunks, preview_chunks
from .pdf_tools import read_pdf_local, read_pdf_from_s3
from .text_tools import clean_text, clean_financial_text
from .chunk_tools import semantic_chunker
from .vector_tools import vector_upsert

def pdf_to_text_artifact_local(path: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text = read_pdf_local(path)
    md = {"source": "pdf_local", "path": path, **(metadata or {})}
    return put_text(text, metadata=md)

def pdf_to_text_artifact_s3(s3_uri: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text = read_pdf_from_s3(s3_uri)
    md = {"source": "pdf_s3", "s3_uri": s3_uri, **(metadata or {})}
    return put_text(text, metadata=md)

def artifact_put_text(text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return put_text(text, metadata=metadata)

def artifact_preview(artifact_id: str, max_chars: int = 800) -> str:
    return preview_text(artifact_id, max_chars=max_chars)

def clean_text_artifact(artifact_id: str, mode: str = "basic") -> Dict[str, Any]:
    mode = (mode or "basic").lower().strip()
    t = get_text(artifact_id)
    if mode == "financial":
        out = clean_financial_text(t)
        md = {"parent": artifact_id, "clean_mode": "financial"}
    else:
        out = clean_text(t)
        md = {"parent": artifact_id, "clean_mode": "basic"}
    return put_text(out, metadata=md)

def chunk_text_artifact(artifact_id: str, strategy: str = "recursive", max_chars: int = 1200, overlap: int = 120) -> Dict[str, Any]:
    t = get_text(artifact_id)
    chunks = semantic_chunker(text=t, strategy=strategy, max_chars=max_chars, overlap=overlap)
    return put_chunks(chunks, metadata={"parent": artifact_id, "strategy": strategy, "max_chars": max_chars, "overlap": overlap})

def chunks_preview(chunks_id: str, limit: int = 3) -> List[str]:
    return preview_chunks(chunks_id, limit=limit)

def vector_upsert_from_chunks(chunks_id: str, index_name: str = "default", source: str = "artifact") -> Dict[str, Any]:
    chunks = get_chunks(chunks_id)
    metas = [{"source": source, "chunks_id": chunks_id, "i": i} for i in range(len(chunks))]
    return vector_upsert(chunks=chunks, index_name=index_name, metadatas=metas)

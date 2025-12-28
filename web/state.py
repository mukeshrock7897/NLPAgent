from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import os
import re
from web import db

# A deterministic pipeline that works with your MCP tools.
PIPELINE_TEMPLATE = [
    {"tool": "read_pdf_local_tool", "title": "Read uploaded PDF"},
    {"tool": "clean_text_tool", "title": "Clean extracted text"},
    {"tool": "semantic_chunker_tool", "title": "Chunk text"},
    {"tool": "embed_texts_tool", "title": "Create embeddings"},
    {"tool": "vector_upsert_tool", "title": "Upsert to vector index"},
]

DEFAULT_INDEX_NAME = "nlpagent-default"


def ensure_chat(session_id: str, title: str = "New Chat", user_id: Optional[int] = None) -> None:
    if not db.get_chat(session_id, user_id=user_id):
        db.upsert_chat(session_id, title, user_id=user_id)


def get_openai_messages(session_id: str, limit: int = 30) -> List[Dict[str, str]]:
    # Only user + assistant messages. Never store "tool" messages here.
    raw = db.list_messages(session_id, limit=200)
    msgs = [{"role": r["role"], "content": r["content"]} for r in raw if r["role"] in ("user", "assistant")]
    return msgs[-limit:]


def pipeline_start(session_id: str, pdf_path: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Creates a pipeline run in DB and returns the first pending step.
    """
    ensure_chat(session_id, user_id=user_id)

    # context stores intermediate results but we never show it in UI.
    base = os.path.basename(pdf_path or "")
    stem = os.path.splitext(base)[0]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-") or "document"
    slug = slug[:24]
    short_id = session_id[:8]
    index_name = f"nlpagent-{short_id}-{slug}"
    context = {
        "pdf_path": pdf_path,
        "raw_text": None,
        "clean_text": None,
        "chunks": None,
        "embeddings": None,
        "index_name": index_name,
    }
    db.create_pipeline_run(session_id, json.dumps(context))

    # Initialize steps: first is pending, rest queued
    for i, s in enumerate(PIPELINE_TEMPLATE):
        status = "pending" if i == 0 else "queued"
        db.upsert_step(session_id, i, s["tool"], s["title"], status)

    db.set_pipeline_status(session_id, "blocked")
    db.set_current_step(session_id, 0)

    return {
        "idx": 0,
        "tool_name": PIPELINE_TEMPLATE[0]["tool"],
        "title": PIPELINE_TEMPLATE[0]["title"],
        "status": "pending",
    }


def pipeline_next_pending(session_id: str) -> Optional[Dict[str, Any]]:
    run = db.get_pipeline_run(session_id)
    if not run:
        return None
    steps = db.list_steps(session_id)
    for s in steps:
        if s["status"] == "pending":
            return s
    return None

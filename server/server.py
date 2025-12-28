"""NLPAGENT MCP Server (FastMCP, HTTP transport)

Run:
  python server/server.py

MCP endpoint:
  http://127.0.0.1:8000/mcp
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

if __name__ == "__main__" and __package__ is None:
    # Allow running as "python server/server.py" from the repo root.
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from server.app.tools.text_tools import clean_text, clean_financial_text, tokenize
from server.app.tools.pdf_tools import read_pdf_local, read_pdf_from_s3
from server.app.tools.chunk_tools import semantic_chunker
from server.app.tools.embed_tools import embed_texts
from server.app.tools.vector_tools import vector_upsert, vector_query, vector_stats
from server.app.tools.eval_tools import evaluate_retrieval
from server.app.tools.artifact_tools import (
    pdf_to_text_artifact_local,
    pdf_to_text_artifact_s3,
    artifact_put_text,
    artifact_preview,
    clean_text_artifact,
    chunk_text_artifact,
    chunks_preview,
    vector_upsert_from_chunks,
)

load_dotenv()
mcp = FastMCP("NLPAGENT-MCP")

@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")

# -------------------------
# Basic tools
# -------------------------
@mcp.tool
def clean_text_tool(text: str) -> str:
    return clean_text(text)

@mcp.tool
def clean_financial_text_tool(text: str) -> str:
    return clean_financial_text(text)

@mcp.tool
def tokenize_tool(text: str, mode: str = "regex") -> List[str]:
    return tokenize(text, mode=mode)

@mcp.tool
def semantic_chunker_tool(text: str, strategy: str = "paragraph", max_chars: int = 1200, overlap: int = 120) -> List[str]:
    return semantic_chunker(text=text, strategy=strategy, max_chars=max_chars, overlap=overlap)

@mcp.tool
def read_pdf_local_tool(path: str) -> str:
    return read_pdf_local(path)

@mcp.tool
def read_pdf_from_s3_tool(s3_uri: str) -> str:
    return read_pdf_from_s3(s3_uri)

@mcp.tool
def embed_texts_tool(texts: List[str], model_name: Optional[str] = None) -> List[List[float]]:
    return embed_texts(texts=texts, model_name=model_name)

@mcp.tool
def vector_upsert_tool(
    chunks: List[str],
    index_name: str = "default",
    metadatas: Optional[List[Dict[str, Any]]] = None,
    embeddings: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    return vector_upsert(
        chunks=chunks,
        index_name=index_name,
        metadatas=metadatas,
        embeddings=embeddings,
    )

@mcp.tool
def vector_query_tool(query: str, index_name: str = "default", top_k: int = 5) -> Dict[str, Any]:
    return vector_query(query=query, index_name=index_name, top_k=top_k)

@mcp.tool
def vector_stats_tool(index_name: str = "default") -> Dict[str, Any]:
    return vector_stats(index_name=index_name)

@mcp.tool
def evaluate_retrieval_tool(query: str, index_name: str, expected_terms: List[str], top_k: int = 5) -> Dict[str, Any]:
    return evaluate_retrieval(query=query, index_name=index_name, expected_terms=expected_terms, top_k=top_k)

# -------------------------
# Artifact-based tools (preferred for LLM)
# -------------------------
@mcp.tool
def pdf_to_text_artifact_local_tool(path: str) -> Dict[str, Any]:
    return pdf_to_text_artifact_local(path)

@mcp.tool
def pdf_to_text_artifact_s3_tool(s3_uri: str) -> Dict[str, Any]:
    return pdf_to_text_artifact_s3(s3_uri)

@mcp.tool
def artifact_put_text_tool(text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return artifact_put_text(text, metadata=metadata)

@mcp.tool
def artifact_preview_tool(artifact_id: str, max_chars: int = 800) -> str:
    return artifact_preview(artifact_id, max_chars=max_chars)

@mcp.tool
def clean_text_artifact_tool(artifact_id: str, mode: str = "basic") -> Dict[str, Any]:
    return clean_text_artifact(artifact_id, mode=mode)

@mcp.tool
def chunk_text_artifact_tool(artifact_id: str, strategy: str = "recursive", max_chars: int = 1200, overlap: int = 120) -> Dict[str, Any]:
    return chunk_text_artifact(artifact_id, strategy=strategy, max_chars=max_chars, overlap=overlap)

@mcp.tool
def chunks_preview_tool(chunks_id: str, limit: int = 3) -> List[str]:
    return chunks_preview(chunks_id, limit=limit)

@mcp.tool
def vector_upsert_from_chunks_tool(chunks_id: str, index_name: str = "default", source: str = "artifact") -> Dict[str, Any]:
    return vector_upsert_from_chunks(chunks_id, index_name=index_name, source=source)

if __name__ == "__main__":
    host = os.getenv("NLPAGENT_MCP_HOST", "127.0.0.1")
    port = int(os.getenv("NLPAGENT_MCP_PORT", "8000"))
    mcp.run(transport="http", host=host, port=port)

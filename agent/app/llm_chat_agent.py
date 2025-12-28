from __future__ import annotations

import os
from typing import List

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI


def system_prompt() -> str:
    return """You are NLPAGENT — an Agentic NLP Pipeline product.

Product rules:
- Do NOT print raw tool outputs, raw JSON dumps, or long extracted text.
- Keep responses crisp and structured with short headings + bullets.
- If tools are needed, propose exactly ONE tool call at a time.
- The user must approve every tool run. When approval is needed, say it clearly in one line.

If the user uploads a PDF, the message will include:
Attachments:
- data/uploads/<file>.pdf

Common pipeline:
1) read_pdf_local_tool(path)
2) clean_text_tool(text) OR clean_financial_text_tool(text)
3) semantic_chunker_tool(text)
4) embed_texts_tool(texts/chunks)
5) vector_upsert_tool(vectors + metadata)
6) (optional) evaluate_retrieval_tool(query/test)

If user says “run the pipeline”, run this pipeline for the uploaded PDF step-by-step with approvals.
"""


def _require_openai_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return "OPENAI_API_KEY is missing. Add it to .env and restart."
    return None


def llm_plan(messages: List[BaseMessage], tools: list):
    missing = _require_openai_key()
    if missing:
        return AIMessage(content=missing, tool_calls=[])

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))

    llm = ChatOpenAI(model=model, temperature=temperature)
    llm_tools = llm.bind_tools(tools) if tools else llm

    out = llm_tools.invoke(messages)

    tool_calls = getattr(out, "tool_calls", None) or []
    content = getattr(out, "content", "") or ""

    # enforce ONE tool call only (sequential approvals)
    if len(tool_calls) > 1:
        tool_calls = [tool_calls[0]]

    # if tool call exists but no visible content, fix UX
    if tool_calls and not content.strip():
        tc0 = tool_calls[0]
        content = f"Ready to run `{tc0.get('name')}`. Please approve to continue."

    return AIMessage(content=content, tool_calls=tool_calls)

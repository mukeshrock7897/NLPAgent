# NLPAGENT Architecture (LLM-first + Human Approval)

## High-level
- **OpenAI LLM** decides the workflow purely through chat (tool calling).
- **MCP server (FastMCP)** hosts the real capabilities (tools).
- **Human approval gate** sits between the LLM and tool execution.
- **SQLite artifact store** keeps large intermediate outputs out of the LLM context.

## Preferred tool path (large PDFs)
1. pdf_to_text_artifact_local_tool(path) -> artifact_id
2. clean_text_artifact_tool(artifact_id, mode=financial/basic) -> artifact_id
3. chunk_text_artifact_tool(artifact_id) -> chunks_id
4. vector_upsert_from_chunks_tool(chunks_id, index_name) -> persists into ChromaDB
5. vector_query_tool(query, index_name) -> retrieve

## Human approval
The UI pauses on every tool call proposal and requires Approve/Reject.

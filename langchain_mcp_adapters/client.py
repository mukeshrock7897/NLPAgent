from __future__ import annotations

import json
from typing import Any, Dict, List

from fastmcp import Client as MCPClient
from langchain_core.tools import StructuredTool


class MultiServerMCPClient:
    """Lightweight MCP-to-LangChain adapter used when langchain-mcp-adapters is unavailable."""

    def __init__(self, servers: Dict[str, Any], tool_name_prefix: bool = True) -> None:
        self._servers = servers
        self._tool_name_prefix = tool_name_prefix

    async def __aenter__(self) -> "MultiServerMCPClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    async def get_tools(self) -> List[StructuredTool]:
        tools: List[StructuredTool] = []
        for server_name, server_cfg in self._servers.items():
            client_cfg = self._client_config(server_name, server_cfg)
            async with MCPClient(client_cfg) as client:
                mcp_tools = await client.list_tools()
            for mcp_tool in mcp_tools:
                tools.append(self._wrap_tool(server_name, client_cfg, mcp_tool))
        return tools

    def _wrap_tool(self, server_name: str, client_cfg: Any, mcp_tool: Any) -> StructuredTool:
        tool_name = (
            f"{server_name}__{mcp_tool.name}" if self._tool_name_prefix else mcp_tool.name
        )
        description = mcp_tool.description or getattr(mcp_tool, "title", "") or ""
        args_schema = mcp_tool.inputSchema or {"type": "object", "properties": {}}

        async def _invoke(**kwargs: Any) -> Any:
            async with MCPClient(client_cfg) as client:
                args = kwargs or None
                result = await client.call_tool(
                    mcp_tool.name, arguments=args, raise_on_error=False
                )
            return self._unwrap_result(result)

        return StructuredTool(
            name=tool_name,
            description=description,
            args_schema=args_schema,
            coroutine=_invoke,
        )

    def _client_config(self, server_name: str, server_cfg: Any) -> Any:
        if isinstance(server_cfg, dict):
            if "mcpServers" in server_cfg:
                return server_cfg
            return {server_name: server_cfg}
        return server_cfg

    def _unwrap_result(self, result: Any) -> Any:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured

        content = getattr(result, "content", None)
        if not content:
            return result

        texts: List[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                texts.append(text)
        if not texts:
            return result.model_dump() if hasattr(result, "model_dump") else result

        joined = "\n".join(texts).strip()
        if joined and (joined.startswith("{") or joined.startswith("[")):
            try:
                return json.loads(joined)
            except Exception:
                return joined
        return joined

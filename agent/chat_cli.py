"""NLPAGENT Chat CLI (OpenAI Brain + Human Approval)

Run:
  python agent/chat_cli.py

Requirements:
  - MCP server running (MCP_URL)
  - OPENAI_API_KEY set
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.app.llm_chat_agent import system_prompt, llm_invoke, tool_result_to_message

load_dotenv()

async def load_tools():
    url = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")
    client = MultiServerMCPClient({"nlpagent": {"transport": "http", "url": url}}, tool_name_prefix=False)
    async with client:
        return await client.get_tools()

def main():
    tools = asyncio.run(load_tools())
    tool_map = {t.name: t for t in tools}

    messages: List[BaseMessage] = [SystemMessage(content=system_prompt())]
    print("NLPAGENT chat CLI ready. Type 'exit' to quit.")

    while True:
        user = input("\nYou> ").strip()
        if user.lower() in {"exit", "quit"}:
            break
        messages.append(HumanMessage(content=user))

        while True:
            ai = llm_invoke(messages, tools)
            messages.append(ai)

            tcalls = getattr(ai, "tool_calls", None) or []
            if tcalls:
                tc = tcalls[0]
                name = tc.get("name")
                args = tc.get("args") or {}
                tcid = tc.get("id")
                print(f"\nAssistant proposes: {name}({json.dumps(args, ensure_ascii=False)})")
                ok = input("Approve? (y/n) ").strip().lower()
                if ok != "y":
                    messages.append(HumanMessage(content="Tool call rejected by human. Propose an alternative."))
                    continue
                try:
                    result = asyncio.run(tool_map[name].ainvoke(args))
                except Exception as e:
                    result = {"error": str(e), "tool": name, "args": args}
                messages.append(tool_result_to_message(tcid, result))
                continue
            else:
                print(f"\nAssistant> {ai.content}")
                break

if __name__ == "__main__":
    main()

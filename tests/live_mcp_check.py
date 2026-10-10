"""Opt-in check of the MCP server over real stdio against a running engine.

    PAPER_AGENT_TOKEN=... python -m tests.live_mcp_check

Lists the tools and calls the read-only get_guardrails and get_overview. It never trades.
"""

import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "paper_engine.mcp_server"],
        env={
            **os.environ,
            "PAPER_ENGINE_URL": os.environ.get("PAPER_ENGINE_URL", "http://127.0.0.1:8000"),
        },
    )
    async with Client(params) as client:
        tools = [t.name for t in (await client.list_tools()).tools]
        result = {"tools": tools}
        for name in ("get_guardrails", "get_overview"):
            response = await client.call_tool(name, {})
            result[name] = json.loads(response.content[0].text)
        print(json.dumps(result, indent=2)[:3000])


if __name__ == "__main__":
    asyncio.run(main())

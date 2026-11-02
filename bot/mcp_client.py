"""One local MCP subprocess and a serialized client session."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parent.parent


class MCPClient:
    def __init__(self, session):
        self.session=session
        self.lock=asyncio.Lock()

    async def call(self,name,arguments=None):
        async with self.lock:
            result=await self.session.call_tool(name,arguments or {})
        if result.isError:
            raise ValueError(' '.join(getattr(c,'text','') for c in result.content))
        if result.structuredContent is not None:
            value=result.structuredContent
            return value.get('result') if isinstance(value,dict) and set(value)=={'result'} else value
        parts=[c.text for c in result.content if getattr(c,'type','')=='text']
        if not parts: return None
        try: return json.loads(parts[0])
        except json.JSONDecodeError: return parts[0]

    async def tools(self):
        async with self.lock: return (await self.session.list_tools()).tools


@asynccontextmanager
async def open_mcp():
    params=StdioServerParameters(command=sys.executable,args=['-m','mcp_server.server'],cwd=str(ROOT),
                                 env={**os.environ,'PYTHONUTF8':'1'})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            yield MCPClient(session)

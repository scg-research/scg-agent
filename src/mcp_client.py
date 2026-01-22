import os
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@asynccontextmanager
async def create_mcp_client(cwd: Path | str) -> ClientSession:
    """
    Create a client session connected to the SCG experiments MCP server.

    Args:
        cwd: The working directory where the server command should run (scg-experiments root).
    """
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "src.mcp_server"],
        cwd=str(cwd),
        env=dict(os.environ),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session

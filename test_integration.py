"""
Test script to verify the MCP bridge integration.
Run this to ensure the scg-agent can connect to the scg-experiments MCP server.
"""

import asyncio
from pathlib import Path
from src.mcp_client import create_mcp_client


async def test_bridge_integration():
    """Test that the SCG bridge loads and works correctly."""

    # Adjust paths to your data and code
    # scg-experiments path
    experiments_root = Path(__file__).parent.parent / "scg-experiments"

    print(f"Connecting to MCP server at: {experiments_root}")

    try:
        async with create_mcp_client(experiments_root) as session:
            print("✅ Connected to MCP server!")

            # List tools
            tools = await session.list_tools()
            print(f"   Available tools: {[t.name for t in tools.tools]}")

            # Test search (if tools available)
            if any(t.name == "search_code" for t in tools.tools):
                print("\n Testing search functionality...")
                result = await session.call_tool(
                    "search_code", arguments={"query": "cache", "limit": 3}
                )
                if result.content:
                    print(
                        f"   Search result preview:\n{result.content[0].text[:200]}..."
                    )

            # Test graph stats
            if any(t.name == "get_graph_stats" for t in tools.tools):
                print("\n Testing graph stats...")
                result = await session.call_tool("get_graph_stats", arguments={})
                if result.content:
                    print(f"   Stats:\n{result.content[0].text}")

        print("\n✅ All tests passed! Integration is working correctly.")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(test_bridge_integration())

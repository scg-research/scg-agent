"""
LangChain-compatible tool wrappers for SCGBridge methods.

These tools wrap the SCGBridge functionality for use with LangGraph agents.
"""

from typing import List
from langchain_core.tools import tool


from mcp import ClientSession


def create_scg_tools(session: ClientSession) -> list:
    """Create LangChain tools that wrap MCP client methods.

    Args:
        session: Active MCP ClientSession

    Returns:
        List of LangChain tool functions
    """

    @tool
    def search_symbols(query: str, limit: int = 10) -> str:
        """Search for code symbols (classes, methods, functions) matching the query.

        Args:
            query: Search query string (e.g., "cache manager", "parse json")
            limit: Maximum number of results to return (default: 10)

        Returns:
            Formatted string with matching symbols and their metadata
        """
        try:
            pass
        except Exception as e:
            return f"Error: {str(e)}"
        return "Not implemented yet - need async wrapper"

    @tool
    async def search_symbols(query: str, limit: int = 10) -> str:
        """Search for code symbols (classes, methods, functions) matching the query.

        Args:
            query: Search query string (e.g., "cache manager", "parse json")
            limit: Maximum number of results to return (default: 10)

        Returns:
            Formatted string with matching symbols and their metadata
        """
        result = await session.call_tool(
            "search_code", arguments={"query": query, "limit": limit}
        )
        if not result.content:
            return "No content returned."
        return result.content[0].text

    @tool
    async def get_source_code(node_id: str, context_padding: int = 3) -> str:
        """Get the source code for a specific node.

        Args:
            node_id: The unique identifier of the node (from search results)
            context_padding: Number of lines before/after to include (default: 3)

        Returns:
            Source code string or error message if not found
        """
        result = await session.call_tool(
            "get_node_source",
            arguments={"node_id": node_id, "context_padding": context_padding},
        )
        if not result.content:
            return "No content returned."
        return result.content[0].text

    @tool
    async def get_subgraph_context(node_ids: List[str], hops: int = 1) -> str:
        """Get a context subgraph around the specified nodes.

        Args:
            node_ids: List of node IDs to center the subgraph around
            hops: Number of graph hops to expand (default: 1)

        Returns:
            Human-readable context describing the subgraph
        """
        result = await session.call_tool(
            "get_node_context", arguments={"node_ids": node_ids, "hops": hops}
        )
        if not result.content:
            return "No content returned."
        return result.content[0].text

    @tool
    async def get_graph_stats() -> str:
        """Get statistics about the code graph.

        Returns:
            Formatted statistics about the code graph including node and edge counts.
        """
        result = await session.call_tool("get_graph_stats", arguments={})
        if not result.content:
            return "No content returned."
        return result.content[0].text

    return [search_symbols, get_source_code, get_subgraph_context, get_graph_stats]

"""
LangChain-compatible tool wrappers for SCGBridge methods.

These tools wrap the SCGBridge functionality for use with LangGraph agents.
"""

from typing import Optional, List
from langchain_core.tools import tool
from src import SCGBridge


def create_scg_tools(bridge: SCGBridge) -> list:
    """Create LangChain tools that wrap SCGBridge methods.
    
    Args:
        bridge: Initialized SCGBridge instance
        
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
        results = bridge.search_symbols(query, limit)
        if not results:
            return f"No symbols found matching '{query}'"
        
        output = []
        for r in results:
            output.append(
                f"- {r['display_name']} ({r['type']})\n"
                f"  ID: {r['id']}\n"
                f"  Score: {r['score']:.3f}"
            )
        return "\n".join(output)
    
    @tool
    def get_source_code(node_id: str, context_padding: int = 3) -> str:
        """Get the source code for a specific node.
        
        Args:
            node_id: The unique identifier of the node (from search results)
            context_padding: Number of lines before/after to include (default: 3)
            
        Returns:
            Source code string or error message if not found
        """
        source = bridge.get_source_code(node_id, context_padding)
        if source:
            return source
        return f"No source code available for node '{node_id}'"
    
    @tool
    def get_dependencies(node_id: str, direction: str = "both") -> str:
        """Get dependencies for a node (what it calls and what calls it).
        
        Args:
            node_id: The unique identifier of the node
            direction: "incoming" (callers), "outgoing" (callees), or "both"
            
        Returns:
            Formatted list of dependent nodes
        """
        output = []
        
        if direction in ("outgoing", "both"):
            outgoing = bridge.get_outgoing_dependencies(node_id)
            output.append(f"Outgoing dependencies ({len(outgoing)}):")
            for dep_id in outgoing[:10]:  # Limit to 10
                meta = bridge.get_node_metadata(dep_id)
                name = meta.get("display_name", dep_id) if meta else dep_id
                output.append(f"  - {name}")
        
        if direction in ("incoming", "both"):
            incoming = bridge.get_incoming_dependencies(node_id)
            output.append(f"Incoming dependencies ({len(incoming)}):")
            for dep_id in incoming[:10]:  # Limit to 10
                meta = bridge.get_node_metadata(dep_id)
                name = meta.get("display_name", dep_id) if meta else dep_id
                output.append(f"  - {name}")
        
        return "\n".join(output) if output else f"No dependencies found for '{node_id}'"
    
    @tool
    def get_subgraph_context(node_ids: List[str], hops: int = 1) -> str:
        """Get a context subgraph around the specified nodes.
        
        Args:
            node_ids: List of node IDs to center the subgraph around
            hops: Number of graph hops to expand (default: 1)
            
        Returns:
            Human-readable context describing the subgraph
        """
        subgraph = bridge.get_subgraph(node_ids, hops)
        return bridge.format_context_for_llm(subgraph)
    
    @tool
    def get_node_metadata(node_id: str) -> str:
        """Get detailed metadata for a specific node.
        
        Args:
            node_id: The unique identifier of the node
            
        Returns:
            Formatted metadata string
        """
        meta = bridge.get_node_metadata(node_id)
        if not meta:
            return f"Node '{node_id}' not found"
        
        output = [
            f"Node: {meta.get('display_name', node_id)}",
            f"Type: {meta.get('kind', 'UNKNOWN')}",
            f"File: {meta.get('file_uri', 'N/A')}",
        ]
        
        props = meta.get("properties", {})
        if props:
            output.append("Properties:")
            for k, v in list(props.items())[:5]:  # Limit properties shown
                output.append(f"  {k}: {v}")
        
        return "\n".join(output)
    
    return [search_symbols, get_source_code, get_dependencies, get_subgraph_context, get_node_metadata]

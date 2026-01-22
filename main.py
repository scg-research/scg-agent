"""
Main entry point for the SCG Code Comprehension Agent.

This demonstrates how to:
1. Initialize MCP Client
2. Select a planning strategy
3. Compile and run the graph

To switch strategies, change the graph builder import.
"""

import asyncio
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from src.mcp_client import create_mcp_client

from planning import (
    create_react_graph,
    create_plan_solve_graph,
    create_reflexion_graph,
    create_ada_planner_graph,
    create_lats_graph,
    create_scg_tools,
)


async def run_agent(
    query: str,
    strategy: str = "react",
    data_path: str | None = None,
    code_path: str | None = None,
    verbosity: int = 0,
):
    """Run the code comprehension agent with the specified strategy.

    Args:
        query: The user's question about code
        strategy: Planning strategy to use ("react", "plan_solve", "reflexion", "ada_planner", "lats")
        data_path: Path to SCG data directory (Ignored in MCP mode, server uses defaults)
        code_path: Path to source code directory (Ignored in MCP mode, server uses defaults)
        verbosity: Output verbosity level
    """

    experiments_root = Path(__file__).parent.parent / "scg-experiments"

    if not experiments_root.exists():
        raise FileNotFoundError(f"Could not find scg-experiments at {experiments_root}")

    print(f" Connecting to MCP server in {experiments_root}...")

    async with create_mcp_client(experiments_root) as session:
        print(" Connected to MCP server.")

        tools = create_scg_tools(session)

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
        )

        graph_builders = {
            "react": create_react_graph,
            "plan_solve": create_plan_solve_graph,
            "reflexion": create_reflexion_graph,
            "ada_planner": create_ada_planner_graph,
            "lats": create_lats_graph,
        }

        if strategy not in graph_builders:
            raise ValueError(
                f"Unknown strategy: {strategy}. Choose from: {list(graph_builders.keys())}"
            )

        graph = graph_builders[strategy](llm, tools)

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "final_answer": None,
        }

        if strategy == "plan_solve":
            initial_state["plan"] = []
        elif strategy == "reflexion":
            initial_state.update({"draft_answer": "", "critique": "", "iteration": 0})
        elif strategy == "ada_planner":
            initial_state.update(
                {"current_plan": [], "completed_steps": [], "current_step_index": 0}
            )
        elif strategy == "lats":
            initial_state.update(
                {"candidates": [], "scores": [], "best_path": "", "is_solved": False}
            )

        result = None
        async for event in graph.astream(
            initial_state, stream_mode="updates", config={"recursion_limit": 100}
        ):
            result = event

            if verbosity >= 1:
                for node_name, node_output in event.items():
                    if "messages" in node_output:
                        for message in node_output["messages"]:
                            if hasattr(message, "tool_calls") and message.tool_calls:
                                for tool_call in message.tool_calls:
                                    tool_name = tool_call.get("name", "unknown")
                                    print(f"[Tool Call] {tool_name}")
                                    if verbosity >= 2:
                                        args = tool_call.get("args", {})
                                        print(f"  Args: {args}")

                            if hasattr(message, "type") and message.type == "tool":
                                if verbosity >= 3:
                                    tool_name = getattr(message, "name", "unknown")
                                    content = message.content
                                    if len(str(content)) > 500:
                                        content = str(content)[:500] + "..."
                                    print(f"[Tool Result] {tool_name}:")
                                    print(f"  {content}")

        if result:
            for node_output in result.values():
                if isinstance(node_output, dict) and "final_answer" in node_output:
                    return node_output["final_answer"]

        return "No answer produced."


def main():
    """Example usage."""
    query = "What different caching strategies does Glide support? "

    print(f"Running agent with query: {query}\n")
    print("=" * 50)

    try:
        final_answer = asyncio.run(run_agent(query, strategy="lats", verbosity=2))

        print("\nFinal Answer:")
        print("=" * 50)
        try:
            print(final_answer[-1]["text"])
        except:
            print(final_answer)
    except KeyboardInterrupt:
        print("\nUsing canceled.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()

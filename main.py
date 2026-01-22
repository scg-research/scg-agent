"""
Main entry point for the SCG Code Comprehension Agent.

This demonstrates how to:
1. Initialize SCGBridge and tools
2. Select a planning strategy
3. Compile and run the graph

To switch strategies, change the graph builder import.
"""

from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from src import SCGBridge

from planning import (
    create_react_graph,
    create_plan_solve_graph,
    create_reflexion_graph,
    create_ada_planner_graph,
    create_lats_graph,
    create_scg_tools,
)


def run_agent(
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
        data_path: Path to SCG data directory
        code_path: Path to source code directory
        verbosity: Output verbosity level:
            - 0: Show only final answer
            - 1: Show final answer and names of called tools
            - 2: Show final answer, tool names, and tool parameters
            - 3: Show final answer, tool names, tool parameters, and tool outputs
        
    Returns:
        The agent's final answer
    """
    # Default paths
    if data_path is None:
        data_path = str(Path(__file__).parent.parent / "scg-experiments" / "data" / "glide")
    if code_path is None:
        code_path = str(Path(__file__).parent.parent / "scg-experiments" / "code" / "glide-4.5.0")
    
    # Initialize components
    bridge = SCGBridge(data_path, code_path=code_path)
    tools = create_scg_tools(bridge)
    
    # Initialize LLM (configure your API key via environment variable)
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
        raise ValueError(f"Unknown strategy: {strategy}. Choose from: {list(graph_builders.keys())}")
    
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
        initial_state.update({"current_plan": [], "completed_steps": [], "current_step_index": 0})
    elif strategy == "lats":
        initial_state.update({"candidates": [], "scores": [], "best_path": "", "is_solved": False})
    
    # Stream through the graph to capture intermediate steps
    result = None
    for event in graph.stream(initial_state, stream_mode="updates", config={"recursion_limit": 100}):
        result = event  # Keep updating to get the final state
        
        if verbosity >= 1:
            # Process each node's output
            for node_name, node_output in event.items():
                if "messages" in node_output:
                    for message in node_output["messages"]:
                        # Check for tool calls (AI message with tool_calls)
                        if hasattr(message, "tool_calls") and message.tool_calls:
                            for tool_call in message.tool_calls:
                                tool_name = tool_call.get("name", "unknown")
                                print(f"[Tool Call] {tool_name}")
                                if verbosity >= 2:
                                    args = tool_call.get("args", {})
                                    print(f"  Args: {args}")
                        
                        # Check for tool results (ToolMessage)
                        if hasattr(message, "type") and message.type == "tool":
                            if verbosity >= 3:
                                tool_name = getattr(message, "name", "unknown")
                                content = message.content
                                # Truncate long outputs
                                if len(str(content)) > 500:
                                    content = str(content)[:500] + "..."
                                print(f"[Tool Result] {tool_name}:")
                                print(f"  {content}")
    
    # Extract final answer from the last state
    if result:
        # Get the final state by finding final_answer in any node output
        for node_output in result.values():
            if isinstance(node_output, dict) and "final_answer" in node_output:
                final_answer = node_output["final_answer"]
                if final_answer:
                    return final_answer
    
    return "No answer produced."


def main():
    """Example usage."""
    query = "What different caching strategies does Glide support? "
    
    print(f"Running agent with query: {query}\n")
    print("=" * 50)
    
    # Verbosity levels:
    # 0 - Only final answer
    # 1 - Final answer + tool names
    # 2 - Final answer + tool names + tool parameters
    # 3 - Final answer + tool names + tool parameters + tool outputs
    final_answer = run_agent(query, strategy="ada_planner", verbosity=3)
    
    print("\nFinal Answer:")
    print("=" * 50)
    try:
        print(final_answer[-1]["text"])
    except:
        print(final_answer)


if __name__ == "__main__":
    main()

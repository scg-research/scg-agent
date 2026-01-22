"""
Plan-and-Solve Framework using LangGraph.

Graph Structure: Planner -> Executor -> END
- Planner node: Generates a complete plan upfront
- Executor node: LLM with tools executes the plan as a batch
- Linear flow: no loops, plan then execute all
"""

from langchain_core.messages import SystemMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition

from .base import PlanningState


PLANNER_SYSTEM_PROMPT = """You are a planning assistant for code analysis tasks.
Given a user's question about code, create a detailed step-by-step plan to answer it.

Your plan should include steps like:
1. Search for specific symbols or concepts
2. Explore dependencies between components
3. Read relevant source code
4. Analyze relationships and patterns

Output your plan as a numbered list of concrete steps. Each step should be actionable.
Do NOT execute the plan - only create it."""


EXECUTOR_SYSTEM_PROMPT = """You are a code analysis executor with access to a Semantic Code Graph.
You have been given a plan to follow. Execute each step using the available tools.

The plan is:
{plan}

Execute all steps systematically and synthesize the results into a comprehensive answer.
When you have completed the plan and gathered enough information, provide your final answer."""


def create_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    planner_prompt: str = PLANNER_SYSTEM_PROMPT,
    executor_prompt: str = EXECUTOR_SYSTEM_PROMPT,
) -> StateGraph:
    """Create a Plan-and-Solve agent graph.

    Args:
        llm: Language model to use
        tools: List of tools for the executor
        planner_prompt: System prompt for planning
        executor_prompt: System prompt for execution

    Returns:
        Compiled StateGraph ready for execution
    """

    llm_with_tools = llm.bind_tools(tools)

    def planner_node(state: PlanningState) -> dict:
        """Generate a complete plan for the task."""
        messages = [SystemMessage(content=planner_prompt), *state["messages"]]

        response = llm.invoke(messages)

        plan_text = response.content
        lines = plan_text.strip().split("\n")
        plan_steps = [
            line.strip()
            for line in lines
            if line.strip()
            and (line.strip()[0].isdigit() or line.strip().startswith("-"))
        ]

        return {
            "messages": [response],
            "plan": plan_steps if plan_steps else [plan_text],
        }

    def executor_node(state: PlanningState) -> dict:
        """Execute the plan using tools."""
        plan = state.get("plan", "")

        executor_system = executor_prompt.format(plan=plan)

        messages = [SystemMessage(content=executor_system), *state["messages"]]

        response = llm_with_tools.invoke(messages)

        return {"messages": [response], "final_answer": response.content}

    tool_node_instance = ToolNode(tools)

    graph = StateGraph(PlanningState)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("tools", tool_node_instance)

    graph.set_entry_point("planner")

    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor", tools_condition, {"tools": "tools", "__end__": END}
    )

    graph.add_edge("tools", "executor")

    return graph.compile()

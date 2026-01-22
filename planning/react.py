"""
ReAct (Reasoning + Acting) Framework using LangGraph.

Graph Structure: Agent <-> Tools cycle
- Agent node: LLM decides to call a tool OR produce final answer
- Tools node: Executes tool calls
- Conditional edge: has_tool_calls -> Tools, else -> END
"""

from typing import Literal
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from .base import BaseAgentState, has_tool_calls


REACT_SYSTEM_PROMPT = """You are a code analysis assistant with access to a Semantic Code Graph.
Your goal is to help users understand code by searching for symbols, exploring dependencies, and reading source code.

Think step by step:
1. Understand what the user is asking about
2. Search for relevant symbols
3. Explore dependencies and relationships
4. Read source code when needed
5. Synthesize your findings into a clear answer

When you have enough information to answer the user's question, provide your final answer directly without calling any more tools."""


def create_graph(
    llm: BaseChatModel, tools: list[BaseTool], system_prompt: str = REACT_SYSTEM_PROMPT
) -> StateGraph:
    """Create a ReAct agent graph.

    Args:
        llm: Language model to use for reasoning
        tools: List of tools the agent can use
        system_prompt: System prompt for the agent

    Returns:
        Compiled StateGraph ready for execution
    """

    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: BaseAgentState) -> dict:
        """Agent node that decides what to do next."""
        messages = state["messages"]

        if not any(m.type == "system" for m in messages):
            from langchain_core.messages import SystemMessage

            messages = [SystemMessage(content=system_prompt)] + list(messages)

        response = llm_with_tools.invoke(messages)

        if not response.tool_calls:
            return {"messages": [response], "final_answer": response.content}

        return {"messages": [response]}

    def should_continue(state: BaseAgentState) -> Literal["tools", "__end__"]:
        """Determine whether to continue to tools or end."""
        if has_tool_calls(state):
            return "tools"
        return "__end__"

    graph = StateGraph(BaseAgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))

    graph.set_entry_point("agent")

    graph.add_conditional_edges(
        "agent", should_continue, {"tools": "tools", "__end__": END}
    )
    graph.add_edge("tools", "agent")

    workflow = graph.compile()
    workflow.get_graph().print_ascii()
    return workflow

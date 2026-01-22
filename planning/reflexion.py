"""
Reflexion Framework using LangGraph.

Graph Structure: Actor <-> Critique cycle
- Actor node: Generates an answer, incorporating previous critique
- Critique node: Evaluates answer quality
- Conditional edge: Good critique -> END, Bad -> loop to Actor
"""

from typing import Literal
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from .base import ReflexionState


ACTOR_SYSTEM_PROMPT = """You are a code analysis assistant with access to a Semantic Code Graph.
Your goal is to provide accurate and comprehensive answers about code.

{critique_context}

Use the available tools to gather information and provide a thorough answer.
Think carefully and be precise in your analysis."""


CRITIQUE_SYSTEM_PROMPT = """You are a critical evaluator of code analysis answers.
Your job is to assess whether an answer is complete, accurate, and helpful.

Evaluate the following answer:
{answer}

Consider:
1. Does it fully address the user's question?
2. Is the information accurate based on the evidence gathered?
3. Is the reasoning clear and well-supported?
4. Are there any obvious gaps or errors?

Respond with EXACTLY one of these formats:
- If the answer is good: "VERDICT: GOOD"
- If the answer needs improvement: "VERDICT: BAD\nFEEDBACK: [your specific feedback for improvement]"

Be constructive in your feedback."""


MAX_ITERATIONS = 3


def create_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    actor_prompt: str = ACTOR_SYSTEM_PROMPT,
    critique_prompt: str = CRITIQUE_SYSTEM_PROMPT,
    max_iterations: int = MAX_ITERATIONS,
) -> StateGraph:
    """Create a Reflexion agent graph.

    Args:
        llm: Language model to use
        tools: List of tools for the actor
        actor_prompt: System prompt for the actor
        critique_prompt: System prompt for the critique
        max_iterations: Maximum Actor-Critique loops

    Returns:
        Compiled StateGraph ready for execution
    """

    llm_with_tools = llm.bind_tools(tools)
    tool_node = ToolNode(tools)

    def actor_node(state: ReflexionState) -> dict:
        """Generate or refine an answer based on critique."""
        critique = state.get("critique", "")

        critique_context = ""
        if critique and "BAD" in critique:
            critique_context = f"""
PREVIOUS ATTEMPT WAS INSUFFICIENT. Please improve based on this feedback:
{critique}

Try again with more thorough research and analysis."""

        system_msg = actor_prompt.format(critique_context=critique_context)
        messages = list(state.get("messages", []))

        if messages and isinstance(messages[0], SystemMessage):
            messages[0] = SystemMessage(content=system_msg)
        else:
            messages.insert(0, SystemMessage(content=system_msg))

        response = llm_with_tools.invoke(messages)

        return {"messages": [response], "draft_answer": response.content}

    def critique_node(state: ReflexionState) -> dict:
        """Evaluate the current answer."""
        draft = state.get("draft_answer", "")
        iteration = state.get("iteration", 0)

        critique_system = critique_prompt.format(answer=draft)
        messages = [
            SystemMessage(content=critique_system),
            HumanMessage(content="Please evaluate this answer."),
        ]

        response = llm.invoke(messages)

        print("=" * 50)
        print("Critique:")
        print(response.content)
        print("=" * 50)

        return {"critique": response.content, "iteration": iteration + 1}

    def finalize_node(state: ReflexionState) -> dict:
        """Finalize the answer."""
        return {"final_answer": state.get("draft_answer", "")}

    def decide_actor_path(state: ReflexionState) -> Literal["tools", "critique"]:
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return "critique"

    def should_continue(state: ReflexionState) -> Literal["actor", "__end__"]:
        """Determine whether to continue refining or end."""
        critique = state.get("critique", "")
        iteration = state.get("iteration", 0)

        if "VERDICT: GOOD" in critique or iteration >= max_iterations:
            return "__end__"

        return "actor"

    graph = StateGraph(ReflexionState)

    graph.add_node("actor", actor_node)
    graph.add_node("tools", tool_node)
    graph.add_node("critique", critique_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("actor")

    graph.add_conditional_edges(
        "actor", decide_actor_path, {"tools": "tools", "critique": "critique"}
    )

    graph.add_edge("tools", "actor")

    graph.add_conditional_edges(
        "critique", should_continue, {"actor": "actor", "__end__": "finalize"}
    )

    graph.add_edge("finalize", END)

    workflow = graph.compile()
    workflow.get_graph().print_ascii()
    return workflow

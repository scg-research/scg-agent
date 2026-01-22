"""
Base types, utilities, and shared components for LangGraph planning frameworks.
"""

from typing import TypedDict, List, Optional, Annotated
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langgraph.graph import add_messages


class BaseAgentState(TypedDict):
    """Base state shared by all planning frameworks."""

    messages: Annotated[List[BaseMessage], add_messages]
    final_answer: Optional[str]


class PlanningState(BaseAgentState):
    """State for plan-based frameworks (Plan-and-Solve, AdaPlanner)."""

    plan: List[str]


class ReflexionState(BaseAgentState):
    """State for Reflexion framework with critique loop."""

    draft_answer: str
    critique: str
    iteration: int


class AdaPlannerState(BaseAgentState):
    """State for AdaPlanner with adaptive re-planning."""

    current_plan: List[str]
    completed_steps: List[str]
    current_step_index: int
    executor_messages: List[BaseMessage]


class LATSState(BaseAgentState):
    """State for LATS (Best-of-N) framework."""

    candidates: List[dict]
    scores: List[float]
    best_path: str
    is_solved: bool
    current_candidate_index: int


def has_tool_calls(state: BaseAgentState) -> bool:
    """Check if the last message contains tool calls."""
    messages = state.get("messages", [])
    if not messages:
        return False
    last_message = messages[-1]
    return hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0


def get_last_ai_message(state: BaseAgentState) -> Optional[AIMessage]:
    """Get the most recent AI message from state."""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage):
            return msg
    return None


def format_tool_results(tool_messages: List[ToolMessage]) -> str:
    """Format tool results into a readable string."""
    results = []
    for msg in tool_messages:
        results.append(f"Tool: {msg.name}\nResult: {msg.content}")
    return "\n\n".join(results)

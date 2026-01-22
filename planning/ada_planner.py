"""
AdaPlanner (Adaptive Planning) Framework using LangGraph.

Graph Structure: Planner -> Executor <-> Tools -> Record -> Re-Planner cycle
- Planner node: Creates initial plan
- Executor node: Invokes LLM to decide on tool calls for current step
- Tools node: Executes tool calls
- Record node: Records step completion
- Re-Planner node: Observes output, decides to continue/modify/finish
- Conditional edges: Based on tool calls and re-planner decision
"""

from typing import Literal
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END

from .base import AdaPlannerState


PLANNER_SYSTEM_PROMPT = """You are a strategic planner for code analysis tasks.
Create a step-by-step plan to answer the user's question about code.

Output your plan as a numbered list. Each step should be:
1. Specific and actionable
2. Focused on a single action (search, explore, read, analyze)
3. Building towards the final answer

Example format:
1. Search for classes related to "caching"
2. Get dependencies of the main cache manager
3. Read the source code of key methods
4. Analyze the caching strategy used"""


EXECUTOR_SYSTEM_PROMPT = """You are executing step {step_num} of a code analysis plan.

The full plan is:
{plan}

Current step to execute: {current_step}

Previously completed steps:
{completed_steps}

Execute ONLY the current step using the available tools. Be thorough but focused."""


REPLANNER_SYSTEM_PROMPT = """You are an adaptive planner reviewing the progress of a code analysis task.

Original question: {question}

Current plan:
{plan}

Completed steps and their results:
{completed_info}

Current step index: {current_index} of {total_steps}

Based on the results so far, decide what to do next. Respond with EXACTLY one of:
1. "DECISION: CONTINUE" - if the plan is working and we should proceed to the next step
2. "DECISION: MODIFY\nNEW_PLAN: [your revised plan as numbered list]" - if we need to change approach
3. "DECISION: FINISHED\nANSWER: [your final answer]" - if we have enough information to answer

Be decisive and practical."""


def create_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    planner_prompt: str = PLANNER_SYSTEM_PROMPT,
    executor_prompt: str = EXECUTOR_SYSTEM_PROMPT,
    replanner_prompt: str = REPLANNER_SYSTEM_PROMPT,
) -> StateGraph:
    """Create an AdaPlanner agent graph.

    Args:
        llm: Language model to use
        tools: List of tools for execution
        planner_prompt: System prompt for initial planning
        executor_prompt: System prompt for step execution
        replanner_prompt: System prompt for re-planning

    Returns:
        Compiled StateGraph ready for execution
    """

    llm_with_tools = llm.bind_tools(tools)

    def planner_node(state: AdaPlannerState) -> dict:
        """Create the initial plan."""
        messages = [SystemMessage(content=planner_prompt), *state.get("messages", [])]

        response = llm.invoke(messages)

        lines = response.content.strip().split("\n")
        plan_steps = [
            line.strip()
            for line in lines
            if line.strip()
            and (line.strip()[0].isdigit() or line.strip().startswith("-"))
        ]

        print("=" * 50)
        print("Initial Plan:")
        for i, step in enumerate(plan_steps):
            print(f"{i + 1}. {step}")
        print("=" * 50)

        return {
            "messages": [response],
            "current_plan": plan_steps if plan_steps else [response.content],
            "completed_steps": [],
            "current_step_index": 0,
        }

    def executor_node(state: AdaPlannerState) -> dict:
        """Execute the current step."""
        plan = state.get("current_plan", [])
        step_index = state.get("current_step_index", 0)
        completed = state.get("completed_steps", [])
        executor_messages = state.get("executor_messages", [])

        if step_index >= len(plan):
            return {"messages": []}

        current_step = plan[step_index]

        plan_formatted = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
        completed_formatted = "\n".join(completed) if completed else "None yet"

        system_msg = executor_prompt.format(
            step_num=step_index + 1,
            plan=plan_formatted,
            current_step=current_step,
            completed_steps=completed_formatted,
        )

        if not executor_messages:
            executor_messages = [
                SystemMessage(content=system_msg),
                HumanMessage(content=f"Execute this step: {current_step}"),
            ]

        response = llm_with_tools.invoke(executor_messages)

        return {
            "messages": [response],
            "executor_messages": executor_messages + [response],
        }

    async def tools_node(state: AdaPlannerState) -> dict:
        """Execute tools and add results to executor_messages."""
        from langchain_core.messages import ToolMessage

        messages = state.get("messages", [])
        executor_messages = state.get("executor_messages", [])

        if not messages:
            return {}

        last_message = messages[-1]
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {}

        tool_results = []
        for tool_call in last_message.tool_calls:
            tool_fn = next((t for t in tools if t.name == tool_call["name"]), None)
            if tool_fn:
                try:
                    result = await tool_fn.ainvoke(tool_call["args"])
                    tool_msg = ToolMessage(
                        content=str(result), tool_call_id=tool_call["id"]
                    )
                    tool_results.append(tool_msg)
                except Exception as e:
                    tool_msg = ToolMessage(
                        content=f"Error: {str(e)}", tool_call_id=tool_call["id"]
                    )
                    tool_results.append(tool_msg)

        return {
            "messages": tool_results,
            "executor_messages": executor_messages + tool_results,
        }

    def record_step_node(state: AdaPlannerState) -> dict:
        """Record the completed step result after tool execution."""
        plan = state.get("current_plan", [])
        step_index = state.get("current_step_index", 0)
        completed = state.get("completed_steps", [])
        messages = state.get("messages", [])

        if step_index >= len(plan):
            return {}

        current_step = plan[step_index]

        last_ai_content = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_ai_content = msg.content
                break

        step_result = (
            f"Step {step_index + 1}: {current_step}\nResult: {last_ai_content}"
        )

        return {
            "completed_steps": completed + [step_result],
            "current_step_index": step_index + 1,
            "executor_messages": [],
        }

    def replanner_node(state: AdaPlannerState) -> dict:
        """Decide whether to continue, modify plan, or finish."""
        plan = state.get("current_plan", [])
        completed = state.get("completed_steps", [])
        step_index = state.get("current_step_index", 0)
        messages = state.get("messages", [])

        original_question = ""
        for msg in messages:
            if hasattr(msg, "content") and msg.type == "human":
                original_question = msg.content
                break

        plan_formatted = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
        completed_formatted = "\n".join(completed) if completed else "None"

        system_msg = replanner_prompt.format(
            question=original_question,
            plan=plan_formatted,
            completed_info=completed_formatted,
            current_index=step_index,
            total_steps=len(plan),
        )

        response = llm.invoke(
            [
                SystemMessage(content=system_msg),
                HumanMessage(content="What should we do next?"),
            ]
        )

        content = response.content

        print("=" * 50)
        print("Re-Planner Decision:")
        print(content)
        print("=" * 50)

        if "DECISION: FINISHED" in content:
            answer_match = (
                content.split("ANSWER:")[-1].strip()
                if "ANSWER:" in content
                else content
            )
            return {"messages": [response], "final_answer": answer_match}
        elif "DECISION: MODIFY" in content and "NEW_PLAN:" in content:
            new_plan_text = content.split("NEW_PLAN:")[-1].strip()
            lines = new_plan_text.split("\n")
            new_plan = [
                line.strip()
                for line in lines
                if line.strip()
                and (line.strip()[0].isdigit() or line.strip().startswith("-"))
            ]
            return {
                "messages": [response],
                "current_plan": new_plan if new_plan else plan,
                "current_step_index": 0,
            }
        else:
            return {"messages": [response]}

    def decide_executor_path(state: AdaPlannerState) -> Literal["tools", "record_step"]:
        """Determine whether executor needs to call tools or can record step."""
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"
        return "record_step"

    def should_continue(state: AdaPlannerState) -> Literal["executor", "__end__"]:
        """Determine next action based on re-planner decision."""
        if state.get("final_answer"):
            return "__end__"

        plan = state.get("current_plan", [])
        step_index = state.get("current_step_index", 0)

        if step_index < len(plan):
            return "executor"

        return "__end__"

    graph = StateGraph(AdaPlannerState)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("tools", tools_node)
    graph.add_node("record_step", record_step_node)
    graph.add_node("replanner", replanner_node)

    graph.set_entry_point("planner")

    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        decide_executor_path,
        {"tools": "tools", "record_step": "record_step"},
    )

    graph.add_edge("tools", "executor")

    graph.add_edge("record_step", "replanner")

    graph.add_conditional_edges(
        "replanner", should_continue, {"executor": "executor", "__end__": END}
    )

    workflow = graph.compile()
    workflow.get_graph().print_ascii()
    return workflow

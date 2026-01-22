"""
LATS (Language Agent Tree Search) - Best-of-N Framework using LangGraph.

Graph Structure: Generator -> Tool Executor -> Evaluator -> Selector cycle
- Generator node: Generates N different candidate actions/thoughts
- Tool Executor node: Executes one candidate's tool call at a time
- Evaluator node: Scores each candidate
- Selector node: Picks best path, updates state
- Conditional edge: is_solved -> END, else -> Generator
"""

from typing import Literal, List
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from .base import LATSState


GENERATOR_SYSTEM_PROMPT = """You are generating candidate approaches for a code analysis task.
Generate {num_candidates} DIFFERENT approaches or tool calls to make progress on the task.

Current context:
{context}

Best path so far:
{best_path}

For each candidate, output in this format:
CANDIDATE 1:
Approach: [description of the approach]
Tool: [tool_name]
Args: [tool arguments as JSON]

CANDIDATE 2:
Approach: [description]
Tool: [tool_name]
Args: [tool arguments as JSON]

...and so on.

Make the candidates diverse - try different tools, different search queries, different nodes to explore."""


EVALUATOR_SYSTEM_PROMPT = """You are evaluating candidate approaches for a code analysis task.

Original question: {question}

Here are the candidates with their executed results:
{candidates_with_results}

Score each candidate from 0.0 to 1.0 based on:
- Relevance to the question
- Quality of information obtained
- Progress towards the answer

Output your scores in this exact format:
CANDIDATE 1: [score]
CANDIDATE 2: [score]
...

Then add:
BEST: [candidate number]
SOLVED: [YES/NO] - YES only if we have enough information to fully answer the question"""


SELECTOR_SYSTEM_PROMPT = """You are selecting the best path forward and synthesizing progress.

Best candidate result:
{best_result}

Previous best path:
{previous_path}

If SOLVED, provide the final answer.
Otherwise, update the best_path by adding a summary of what we learned."""


NUM_CANDIDATES = 3
MAX_ITERATIONS = 5


def create_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    num_candidates: int = NUM_CANDIDATES,
    max_iterations: int = MAX_ITERATIONS,
    generator_prompt: str = GENERATOR_SYSTEM_PROMPT,
    evaluator_prompt: str = EVALUATOR_SYSTEM_PROMPT,
    selector_prompt: str = SELECTOR_SYSTEM_PROMPT
) -> StateGraph:
    """Create a LATS (Best-of-N) agent graph.
    
    Args:
        llm: Language model to use
        tools: List of available tools
        num_candidates: Number of candidates to generate per iteration
        max_iterations: Maximum search iterations
        generator_prompt: System prompt for candidate generation
        evaluator_prompt: System prompt for evaluation
        selector_prompt: System prompt for selection
        
    Returns:
        Compiled StateGraph ready for execution
    """
    
    llm_with_tools = llm.bind_tools(tools)
    tool_node = ToolNode(tools)
    iteration_counter = {"count": 0}
    
    def generator_node(state: LATSState) -> dict:
        """Generate N candidate approaches."""
        messages = state.get("messages", [])
        best_path = state.get("best_path", "No progress yet")
        
        # Build context from messages
        context = "\n".join(
            f"{m.type}: {m.content[:200]}..." if len(m.content) > 200 else f"{m.type}: {m.content}"
            for m in messages[-5:]  # Last 5 messages
        )
        
        system_msg = generator_prompt.format(
            num_candidates=num_candidates,
            context=context,
            best_path=best_path
        )
        
        response = llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content="Generate diverse candidate approaches.")
        ])
        
        # Parse candidates
        content = response.content
        candidates = []
        
        # Simple parsing - split by CANDIDATE markers
        parts = content.split("CANDIDATE")[1:]  # Skip text before first CANDIDATE
        for part in parts[:num_candidates]:
            candidates.append({
                "raw": part.strip(),
                "tool": None,
                "args": None,
                "result": None
            })
            
            # Try to extract tool info
            lines = part.strip().split("\n")
            for line in lines:
                if line.startswith("Tool:"):
                    candidates[-1]["tool"] = line.replace("Tool:", "").strip()
                elif line.startswith("Args:"):
                    try:
                        import json
                        args_str = line.replace("Args:", "").strip()
                        candidates[-1]["args"] = json.loads(args_str)
                    except:
                        pass
        
        return {
            "candidates": candidates,
            "current_candidate_index": 0,
            "messages": [response]
        }
    
    def execute_candidate_node(state: LATSState) -> dict:
        """Execute current candidate's tool call using LLM with tools."""
        candidates = state.get("candidates", [])
        current_idx = state.get("current_candidate_index", 0)
        
        if current_idx >= len(candidates):
            return {}
        
        candidate = candidates[current_idx]
        
        if candidate["tool"] and candidate["args"]:
            # Create a message with tool call for the ToolNode to execute
            tool_call = {
                "id": f"call_{current_idx}",
                "name": candidate["tool"],
                "args": candidate["args"]
            }
            ai_msg = AIMessage(content="", tool_calls=[tool_call])
            return {"messages": [ai_msg]}
        
        # No tool to execute, mark as done
        return {"current_candidate_index": current_idx + 1}
    
    def process_tool_result_node(state: LATSState) -> dict:
        """Process the tool result and update the candidate."""
        candidates = state.get("candidates", [])
        current_idx = state.get("current_candidate_index", 0)
        messages = state.get("messages", [])
        
        if current_idx >= len(candidates):
            return {}
        
        # Get the most recent tool message
        result_content = "No result"
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                result_content = str(msg.content)[:500]
                break
        
        # Update candidate with result
        updated_candidates = list(candidates)
        updated_candidates[current_idx] = {
            **updated_candidates[current_idx],
            "result": result_content
        }
        
        return {
            "candidates": updated_candidates,
            "current_candidate_index": current_idx + 1
        }
    
    def decide_candidate_path(state: LATSState) -> Literal["tools", "next_candidate"]:
        """Determine if we need to execute a tool for current candidate."""
        messages = state.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"
        return "next_candidate"
    
    def should_continue_candidates(state: LATSState) -> Literal["execute_candidate", "evaluator"]:
        """Check if there are more candidates to process."""
        candidates = state.get("candidates", [])
        current_idx = state.get("current_candidate_index", 0)
        
        if current_idx < len(candidates):
            return "execute_candidate"
        return "evaluator"
    
    def evaluator_node(state: LATSState) -> dict:
        """Score each candidate."""
        candidates = state.get("candidates", [])
        messages = state.get("messages", [])
        
        # Get original question
        question = ""
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "human":
                question = msg.content
                break
        
        # Format candidates with results
        candidates_text = []
        for i, c in enumerate(candidates):
            result_text = c.get("result", "No result") or "No result"
            candidates_text.append(
                f"CANDIDATE {i+1}:\n{c['raw'][:300]}\nResult: {result_text[:300]}"
            )
        
        system_msg = evaluator_prompt.format(
            question=question,
            candidates_with_results="\n\n".join(candidates_text)
        )
        
        response = llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content="Evaluate and score the candidates.")
        ])
        
        content = response.content
        
        # Parse scores
        scores = []
        for line in content.split("\n"):
            if line.strip().startswith("CANDIDATE") and ":" in line:
                try:
                    score_part = line.split(":")[-1].strip()
                    score = float(score_part.split()[0])
                    scores.append(min(max(score, 0.0), 1.0))
                except:
                    scores.append(0.5)
        
        # Pad with defaults if needed
        while len(scores) < len(candidates):
            scores.append(0.5)
        
        # Check if solved
        is_solved = "SOLVED: YES" in content.upper()
        
        return {
            "scores": scores,
            "is_solved": is_solved,
            "messages": [response]
        }
    
    def selector_node(state: LATSState) -> dict:
        """Select best candidate and update path."""
        candidates = state.get("candidates", [])
        scores = state.get("scores", [])
        best_path = state.get("best_path", "")
        is_solved = state.get("is_solved", False)
        
        iteration_counter["count"] += 1
        
        # Find best candidate
        if candidates and scores:
            best_idx = scores.index(max(scores))
            best_candidate = candidates[best_idx]
            best_result = best_candidate.get("result", "No result")
        else:
            best_result = "No candidates evaluated"
        
        system_msg = selector_prompt.format(
            best_result=best_result[:500],
            previous_path=best_path
        )
        
        response = llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content="Update the best path or provide final answer if solved.")
        ])
        
        new_path = best_path + f"\n\nIteration {iteration_counter['count']}: {response.content[:300]}"
        
        result = {
            "best_path": new_path,
            "messages": [response]
        }
        
        if is_solved or iteration_counter["count"] >= max_iterations:
            result["final_answer"] = response.content
            result["is_solved"] = True
        
        return result
    
    def should_continue(state: LATSState) -> Literal["generator", "__end__"]:
        """Check if we should continue searching."""
        if state.get("is_solved") or state.get("final_answer"):
            return "__end__"
        return "generator"
    
    # Build the graph
    graph = StateGraph(LATSState)
    
    # Add nodes
    graph.add_node("generator", generator_node)
    graph.add_node("execute_candidate", execute_candidate_node)
    graph.add_node("tools", tool_node)
    graph.add_node("process_result", process_tool_result_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("selector", selector_node)
    
    # Set entry point
    graph.set_entry_point("generator")
    
    # Add edges
    # After generator, start executing candidates
    graph.add_edge("generator", "execute_candidate")
    
    # After execute_candidate, decide if we need tools or move to next candidate
    graph.add_conditional_edges(
        "execute_candidate",
        decide_candidate_path,
        {
            "tools": "tools",
            "next_candidate": "process_result"
        }
    )
    
    # After tools, process the result
    graph.add_edge("tools", "process_result")
    
    # After processing result, check if more candidates to process
    graph.add_conditional_edges(
        "process_result",
        should_continue_candidates,
        {
            "execute_candidate": "execute_candidate",
            "evaluator": "evaluator"
        }
    )
    
    graph.add_edge("evaluator", "selector")
    
    graph.add_conditional_edges(
        "selector",
        should_continue,
        {
            "generator": "generator",
            "__end__": END
        }
    )
    
    return graph.compile()

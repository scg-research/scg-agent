from typing import Annotated, Literal, TypedDict
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

@tool
def fetch_code_from_file(file_path: str):
    """Czyta surowy kod z podanej ścieżki pliku."""
    mock_filesystem = {
        "src/auth.py": "def login(user): return 'token' if user.valid else None",
        "src/models.py": "class User: pass"
    }
    return mock_filesystem.get(file_path, "Error: File not found.")

tools = [fetch_code_from_file]

llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", temperature=0)
llm_with_tools = llm.bind_tools(tools)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

def agent_node(state: AgentState):
    return {"messages": [llm_with_tools.invoke(state['messages'])]}

def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = state['messages'][-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return "__end__"

workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(tools))

workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

app = workflow.compile()

user_input = "Pokaż mi jak wygląda funkcja logowania w pliku src/auth.py"
config = {"configurable": {"thread_id": "1"}}
system_message = SystemMessage(content="Jesteś ekspertem SCG. Używaj narzędzi.")

print("--- Start Agenta ---")
inputs = {"messages": [system_message, HumanMessage(content=user_input)]}

for event in app.stream(inputs, config=config, stream_mode="values"):
    last_message = event["messages"][-1]
    print(f"\n{last_message.type}: {last_message.content if hasattr(last_message, 'content') else last_message}")
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print(f"  Tool calls: {last_message.tool_calls}")
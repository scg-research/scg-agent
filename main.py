import json
import os
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

# Import the SCG bridge
from src import SCGBridge

# Initialize the SCG bridge with the path to the data and source code
# Adjust these paths based on your actual data location
DATA_PATH = Path(__file__).parent.parent / "scg-experiments" / "data" / "glide"
CODE_PATH = Path(__file__).parent.parent / "scg-experiments" / "code" / "glide-4.5.0"

scg_bridge = SCGBridge(str(DATA_PATH), code_path=str(CODE_PATH))

@tool
def search_symbols(query: str):
    """
    Wyszukuje symbole (klasy, metody) w projekcie pasujące do zapytania.
    Użyj tego na początku, gdy nie znasz dokładnych nazw klas/metod.
    Zwraca listę pasujących ID węzłów.
    """
    results = scg_bridge.search_symbols(query, limit=10)
    # Format for compatibility with existing agent prompts
    simplified = [{"id": r["id"], "type": r["type"], "display_name": r["display_name"]} for r in results]
    return json.dumps(simplified, indent=2)

@tool
def fetch_source_code(symbol_id: str, context_lines: int = 5):
    """
    Pobiera kod źródłowy dla danego symbolu (np. metody lub klasy).
    Wymaga podania dokładnego ID symbolu (np. z wyniku search_symbols).
    
    Args:
        symbol_id: ID symbolu do pobrania
        context_lines: Liczba linii kontekstu przed i po definicji (domyślnie 5)
    """
    if not scg_bridge.node_exists(symbol_id):
        return f"Error: Symbol '{symbol_id}' not found via SCG Index."
    
    # Try to get source code with context
    source_code = scg_bridge.get_source_code(symbol_id, context_padding=context_lines)
    if source_code:
        metadata = scg_bridge.get_node_metadata(symbol_id)
        location = metadata.get("location") if metadata else None
        
        result = f"Source code for '{symbol_id}':\n"
        if location:
            result += f"Location: {location.uri} (lines {location.startLine}-{location.endLine})\n"
        if context_lines > 0:
            result += f"Context: +/- {context_lines} lines\n"
        result += f"\n{source_code}"
        return result
    
    # If no source code, return metadata information
    metadata = scg_bridge.get_node_metadata(symbol_id)
    if metadata:
        location = metadata.get("location")
        loc_str = f"{location.uri}:{location.startLine}:{location.startCharacter}" if location else "N/A"
        return f"Info: Symbol '{symbol_id}' exists but has no source code available.\nType: {metadata.get('kind', 'UNKNOWN')}\nDisplay Name: {metadata.get('display_name', 'N/A')}\nLocation: {loc_str}"
    
    return f"Info: Symbol '{symbol_id}' exists but has no source code attached (might be an interface or abstract)."

@tool
def analyze_dependencies(symbol_id: str, direction: str = "outgoing"):
    """
    Analizuje graf wywołań (Call Graph) dla danego symbolu.
    Args:
        symbol_id: ID metody/klasy.
        direction: "outgoing" (kogo ta metoda woła?) lub "incoming" (kto woła tę metodę?).
    Przydatne do Impact Analysis (co się zepsuje, jak to zmienię?).
    """
    if not scg_bridge.node_exists(symbol_id):
        return f"Error: Symbol '{symbol_id}' not found."
    
    if direction == "outgoing":
        calls = scg_bridge.get_outgoing_dependencies(symbol_id)
        return json.dumps({"symbol": symbol_id, "calls_external_methods": calls}, indent=2)
    
    elif direction == "incoming":
        called_by = scg_bridge.get_incoming_dependencies(symbol_id)
        return json.dumps({"symbol": symbol_id, "is_called_by": called_by}, indent=2)
    
    return "Error: direction must be 'outgoing' or 'incoming'"

@tool
def calculate_node_metrics(sort_by: str = "incoming_degree", limit: int = 5):
    """
    Oblicza metryki grafowe dla węzłów w projekcie (zgodnie z metodologią SCG).
    
    Args:
        sort_by: Kryterium sortowania: 
                 'incoming_degree' (Impact/Popularność - kto mnie woła?), 
                 'outgoing_degree' (Complexity - kogo ja wołam?), 
                 'total_degree' (Ogólna ważność węzła).
        limit: Liczba zwracanych wyników.
        
    Returns:
        JSON z listą topowych węzłów i ich metrykami.
        Użyj tego, aby znaleźć 'Hotspoty' lub kluczowe elementy architektury (Hubs).
    """
    metrics = scg_bridge.calculate_node_metrics(sort_by=sort_by, limit=limit)
    return json.dumps(metrics, indent=2)

tools = [search_symbols, fetch_source_code, analyze_dependencies, calculate_node_metrics]

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
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

config = {"configurable": {"thread_id": "1"}}

system_message = SystemMessage(content="""
Jesteś Agentem Analizy Oprogramowania (Software Comprehension Agent), zintegrowanym z platformą Semantic Code Graph (SCG).

TWOJA ROLA:
Twoim zadaniem jest odpowiadać na pytania inżynierskie, nawigując po strukturze kodu, a nie zgadując.

DOSTĘPNE NARZĘDZIA:
1. `search_symbols(query)`: Użyj jako pierwsze. Znajdź punkty wejścia (klasy, metody) pasujące do tematu.
2. `analyze_dependencies(symbol_id, direction)`: Kluczowe narzędzie nawigacji.
   - Użyj direction='outgoing', aby zrozumieć, JAK działa metoda (co robi pod spodem).
   - Użyj direction='incoming', aby zrozumieć KONTEKST użycia (impact analysis).
3. `fetch_source_code(symbol_id)`: Użyj, gdy musisz przeanalizować konkretną logikę (np. warunki if, pętle).
4. `calculate_node_metrics(sort_by, limit)`: Użyj, gdy musisz znaleźć najbardziej ryzykowne miejsce (High Impact) oraz najbardziej skomplikowaną metodę, która może wymagać refaktoryzacji.

ZASADY:
- Nie halucynuj nazw metod. Zawsze najpierw ich wyszukaj (`search_symbols`).
- Jeśli uytkownik o konkretny kod/logikę, zawsze uzyj `fetch_source_code` aby pobierac ten kod.
- Odpowiedzi opieraj na faktach pobranych z narzędzi.
- Jeśli użytkownik pyta "co się stanie, gdy zmienię X?", ZAWSZE sprawdź, kto woła X (`analyze_dependencies` z direction='incoming').
""")

def run_scenario(query):
    print(f"----- User: {query} -----")
    inputs = {"messages": [system_message, HumanMessage(content=query)]}
    
    for event in app.stream(inputs, config=config, stream_mode="values"):
        last_msg = event["messages"][-1]
        if last_msg.type == "ai":
            if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls :
                print(f"\nAgent używa narzędzi: {[f"{t['name']}: {t['args']}" for t in last_msg.tool_calls]}")
            else:
                print(f"\nAgent odpowiada: {last_msg.content[-1]["text"]}")
        if last_msg.type == "tool":
            print(f"\nNarzędzie {last_msg.name} zwróciło: {last_msg.content}")


if __name__ == "__main__":
    # Example scenarios - adapt these to your actual codebase
    
    # Get statistics about the loaded graph
    stats = scg_bridge.get_statistics()
    print(f"\n{'='*60}")
    print(f"SCG Statistics:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Total edges: {stats['total_edges']}")
    print(f"  Node kinds: {stats['node_kinds']}")
    print(f"{'='*60}\n")
    
    # Scenario 1: General exploration
    # run_scenario(
    #     "Jakie są główne komponenty tego projektu? Pokaż mi najbardziej kluczowe klasy lub moduły."
    # )
    
    # Scenario 2: Find specific functionality
    # run_scenario(
    #     "Gdzie w kodzie znajduje się logika obsługi cache? Jak to działa?"
    # )
    
    # Scenario 3: Impact analysis
    run_scenario(
        "Planuję zmienić interfejs klasy Cache. Jakie miejsca w kodzie będę musiał zaktualizować?"
    )
    
    # Scenario 4: Code audit
    # run_scenario(
    #     "Przeprowadź audyt projektu. Znajdź najbardziej ryzykowne miejsce (High Impact) oraz najbardziej skomplikowaną metodę."
    # )
import json
from typing import Annotated, Literal, TypedDict
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

SCG_DB = {
    "nodes": {
        "com.eshop.orders.OrderService": {
            "type": "CLASS",
            "loc": 150,
            "doc": "Serwis orkiestrujący proces składania zamówienia.",
            "dependencies": ["com.eshop.payments.PaymentProcessor", "com.eshop.inventory.InventoryService"]
        },
        "com.eshop.orders.OrderService#placeOrder": {
            "type": "METHOD",
            "loc": 45,
            "code": """
    public OrderConfirmation placeOrder(OrderRequest request) {
        // 1. Validate inventory
        if (!inventoryService.checkStock(request.getProductId())) {
            throw new OutOfStockException();
        }
        // 2. Process payment
        PaymentResult payment = paymentProcessor.charge(request.getUser(), request.getAmount());
        if (!payment.isSuccess()) {
            throw new PaymentFailedException();
        }
        // 3. Save order
        Order order = orderRepository.save(new Order(request, payment.getTransactionId()));

        // 4. Send confirmation email
        emailService.sendConfirmation(order.getUser(), order.getTransactionId());

        return order;
    }
            """,
            "calls": [
                "com.eshop.inventory.InventoryService#checkStock",
                "com.eshop.payments.PaymentProcessor#charge",
                "com.eshop.orders.OrderRepository#save",
                "com.eshop.notifications.EmailService#sendConfirmation"
            ],
            "called_by": [
                "com.eshop.api.OrderController#createOrder"
            ]
        },
        "com.eshop.utils.GlobalConfig#get": {
            "type": "METHOD",
            "loc": 10,
            "calls": [],
            "called_by": [
                "com.eshop.orders.OrderService#placeOrder",
                "com.eshop.payments.PaymentProcessor#charge",
                "com.eshop.inventory.InventoryService#checkStock",
                "com.eshop.notifications.EmailService#sendConfirmation" ,
                "com.eshop.api.OrderController#createOrder"
            ]
        },
        "com.eshop.payments.PaymentProcessor#charge": {
            "type": "METHOD",
            "loc": 20,
            "code": "public PaymentResult charge(User user, BigDecimal amount) { ... }",
            "calls": ["com.stripe.StripeClient#createCharge"],
            "called_by": ["com.eshop.orders.OrderService#placeOrder"]
        },
        "com.eshop.inventory.InventoryService#checkStock": {
            "type": "METHOD",
            "loc": 15,
            "code": "public boolean checkStock(String productId) { ... }",
            "calls": [],
            "called_by": ["com.eshop.orders.OrderService#placeOrder"]
        }
    }
}

@tool
def search_symbols(query: str):
    """
    Wyszukuje symbole (klasy, metody) w projekcie pasujące do zapytania.
    Użyj tego na początku, gdy nie znasz dokładnych nazw klas/metod.
    Zwraca listę pasujących ID węzłów.
    """
    results = []
    for node_id, data in SCG_DB["nodes"].items():
        if query.lower() in node_id.lower():
            results.append({"id": node_id, "type": data["type"]})
    return json.dumps(results)

@tool
def fetch_source_code(symbol_id: str):
    """
    Pobiera kod źródłowy dla danego symbolu (np. metody lub klasy).
    Wymaga podania dokładnego ID symbolu (np. z wyniku search_symbols).
    """
    node = SCG_DB["nodes"].get(symbol_id)
    if not node:
        return f"Error: Symbol '{symbol_id}' not found via SCG Index."
    if "code" not in node:
        return f"Info: Symbol '{symbol_id}' exists but has no source code attached (might be an interface or abstract)."
    return node["code"]

@tool
def analyze_dependencies(symbol_id: str, direction: str = "outgoing"):
    """
    Analizuje graf wywołań (Call Graph) dla danego symbolu.
    Args:
        symbol_id: ID metody/klasy.
        direction: "outgoing" (kogo ta metoda woła?) lub "incoming" (kto woła tę metodę?).
    Przydatne do Impact Analysis (co się zepsuje, jak to zmienię?).
    """
    node = SCG_DB["nodes"].get(symbol_id)
    if not node:
        return f"Error: Symbol '{symbol_id}' not found."
    
    if direction == "outgoing":
        calls = node.get("calls", [])
        return json.dumps({"symbol": symbol_id, "calls_external_methods": calls})
    
    elif direction == "incoming":
        called_by = node.get("called_by", [])
        return json.dumps({"symbol": symbol_id, "is_called_by": called_by})
    
    return "Error: direction must be 'outgoing' or 'incoming'"

@tool
def calculate_node_metrics(sort_by: str = "incoming_degree", limit: int = 5):
    """
    Oblicza metryki grafowe dla węzłów w projekcie (zgodnie z metodologią SCG).
    
    Args:
        sort_by: Kryterium sortowania: 
                 'incoming_degree' (Impact/Popularność - kto mnie woła?), 
                 'outgoing_degree' (Complexity - kogo ja wołam?), 
                 'loc' (Rozmiar kodu).
        limit: Liczba zwracanych wyników.
        
    Returns:
        JSON z listą topowych węzłów i ich metrykami.
        Użyj tego, aby znaleźć 'Hotspoty' lub kluczowe elementy architektury (Hubs).
    """
    metrics = []
    
    for node_id, data in SCG_DB["nodes"].items():
        out_degree = len(data.get("calls", [])) + len(data.get("dependencies", []))
        in_degree = len(data.get("called_by", []))
        
        loc = data.get("loc", 0)
        
        metrics.append({
            "id": node_id,
            "type": data["type"],
            "metrics": {
                "incoming_degree": in_degree,
                "outgoing_degree": out_degree,
                "loc": loc
            }
        })
    
    metrics.sort(key=lambda x: x["metrics"].get(sort_by, 0), reverse=True)
    
    return json.dumps(metrics[:limit], indent=2)

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


# Cel: Sprawdzić, czy system znajdzie użycie StripeClient.
run_scenario(
    "Czy korzystamy z zewnętrznych bibliotek do płatności? Jeśli tak, to jakie?"
)

# Cel: Zobaczyć, czy agent sam znajdzie "OrderService" i pobierze kod.
run_scenario(
    "Jak działa proces składania zamówienia w tym projekcie? Interesuje mnie logika biznesowa.", 
)

# Cel: Sprawdzić, czy agent wykryje, że PaymentProcessor jest używany przez OrderService.
run_scenario(
    "Planuję zmienić sygnaturę metody charge w PaymentProcessor. O jakich klasach muszę pamiętać?", 
)

# Cel: Sprawdzić, czy agent użyje narzędzia calculate_node_metrics i zidentyfikuje GlobalConfig#get jako ryzykowne miejsce oraz OrderService#placeOrder jako kandydata na refaktoryzację.
run_scenario(
    "Przeprowadź audyt projektu. Znajdź najbardziej ryzykowne miejsce (High Impact) oraz najbardziej skomplikowaną metodę, która może wymagać refaktoryzacji."
)
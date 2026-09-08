from langgraph.graph import StateGraph,START,END
from src.graph.nodes.intent_parser import intent_parser
from src.graph.nodes.tool_executer import tool_executer
from src.graph.nodes.response_writer import response_writer
from src.graph.state import AgentState
MAX_ITERATIONS = 10
def should_continue(state: AgentState) -> str:
    if state["iterations"] >= MAX_ITERATIONS:
        return "stop"
    if state.get("final_answer"):
        return "stop"
    return "continue"

graph_builder=StateGraph(AgentState)

graph_builder.add_node('intent_parser',intent_parser)
graph_builder.add_node('tool_executer',tool_executer)
graph_builder.add_node('response_writer',response_writer)

graph_builder.set_entry_point('intent_parser')
graph_builder.add_edge('intent_parser','tool_executer')
graph_builder.add_conditional_edges(
    "tool_executer",
    should_continue,
    {
        "continue":"tool_executer",
        "stop":"response_writer"
    }
) 
graph_builder.add_edge('response_writer',END)

agent_graph=graph_builder.compile()

    
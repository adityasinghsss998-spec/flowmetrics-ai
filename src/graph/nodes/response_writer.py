from src.graph.nodes.tool_executer import _generate
from src.graph.state import AgentState


async def response_writer(state: AgentState) -> dict:
    if state.get("final_answer"):
        return {}

    prompt = (
        f"The user asked: {state['user_question']}\n\n"
        f"Here is the real data retrieved to answer it:\n{state['tool_results']}\n\n"
        "Write a clear, direct answer grounded ONLY in this data. "
        "Do not invent numbers that aren't present above."
    )
    response = await _generate(contents=prompt)
    return {"final_answer": response.text}
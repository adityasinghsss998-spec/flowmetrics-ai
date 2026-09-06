from google import genai
from src.config.settings import get_settings
from src.graph.state import AgentState

settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"

async def response_writer(state: AgentState) -> dict:
    if state.get("final_answer"):
        return {}

    prompt = (
        f"The user asked: {state['user_question']}\n\n"
        f"Here is the real data retrieved to answer it:\n{state['tool_results']}\n\n"
        "Write a clear, direct answer grounded ONLY in this data. "
        "Do not invent numbers that aren't present above."
    )
    response = await client.aio.models.generate_content(model=MODEL_ID, contents=prompt)
    return {"final_answer": response.text}
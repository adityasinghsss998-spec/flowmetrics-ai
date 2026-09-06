from google import genai
from google.genai import types

from src.config.settings import get_settings
from src.graph.state import AgentState
from src.tools.tool_definitions import TOOL_FUNCTIONS, execute_tool

settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)

# Verify this is still current at ai.google.dev before you run this —
# check with: python -c "from google import genai; print('ok')"
MODEL_ID = "gemini-3.1-pro-preview"


async def tool_executor(state: AgentState) -> dict:
    """Asks Gemini what to do. If it picks a tool, calls it for real and
    stores the result. Doesn't loop yet — that's Day 3."""

    response = await client.aio.models.generate_content(
        model=MODEL_ID,
        contents=state["user_question"],
        config=types.GenerateContentConfig(
            tools=TOOL_FUNCTIONS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    if not response.function_calls:
        # Model answered directly, no tool needed.
        return {
            "final_answer": response.text,
            "iterations": state["iterations"] + 1,
        }

    call = response.function_calls[0]
    result = await execute_tool(call.name, dict(call.args or {}))

    return {
        "tools_called": state["tools_called"] + [call.name],
        "tool_results": {**state["tool_results"], call.name: result},
        "iterations": state["iterations"] + 1,
    }
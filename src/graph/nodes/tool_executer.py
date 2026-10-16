import asyncio

from google import genai
from google.genai import types

try:
    from src.config.settings import get_settings
    from src.graph.state import AgentState
    from src.tools.tool_definitions import TOOL_FUNCTIONS, execute_tool
except ImportError:
    from src.config.settings import get_settings  # type: ignore[no-redef]
    from src.graph.state import AgentState  # type: ignore[no-redef]
    from src.tools.tool_definitions import TOOL_FUNCTIONS, execute_tool  # type: ignore[no-redef]

settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)

MODEL_ID = settings.GEMINI_MODEL


async def tool_executor(state: AgentState) -> dict:
    """One pass: ask Gemini what to do given the FULL conversation so far.
    Either it answers directly, or it asks for a tool — either way, we
    append what happened to `messages` so the next pass (if any) has
    complete context."""

    response = None
    for attempt in range(4):
        try:
            response = await client.aio.models.generate_content(
                model=MODEL_ID,
                contents=state["messages"],
                config=types.GenerateContentConfig(
                    tools=TOOL_FUNCTIONS,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            break
        except Exception as e:
            if ("429" in str(e) or "503" in str(e) or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e)) and attempt < 3:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                raise
    if response is None:
        return {
            "error": "Gemini returned no response.",
            "final_answer": "Unable to generate response: no response received from Gemini.",
            "iterations": state["iterations"] + 1,
        }

    if not response.candidates or not response.candidates[0].content:
        block_reason = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        finish_reason = getattr(response.candidates[0], "finish_reason", None) if response.candidates else None
        error_msg = f"Gemini returned no content. Block reason: {block_reason}, Finish reason: {finish_reason}"
        return {
            "error": error_msg,
            "final_answer": f"Unable to generate response: {error_msg}",
            "iterations": state["iterations"] + 1,
        }

    model_content = response.candidates[0].content

    if not response.function_calls:
        # Model answered directly, no tool needed.
        return {
            "messages": state["messages"] + [model_content],
            "final_answer": response.text,
            "iterations": state["iterations"] + 1,
        }

    call = response.function_calls[0]
    tool_name = call.name
    if not tool_name:
        return {
            "error": "Function call missing tool name.",
            "final_answer": "Model requested a function call without a valid tool name.",
            "iterations": state["iterations"] + 1,
        }

    try:
        result = await execute_tool(tool_name, dict(call.args or {}))
    except Exception as e:
        result = {"error": f"Tool '{tool_name}' failed: {str(e)}"}

    tool_response_content = types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=tool_name, response={"result": result})],
    )
    return {
        "messages": state["messages"] + [model_content, tool_response_content],
        "tools_called": state["tools_called"] + [tool_name],
        "tool_results": {**state["tool_results"], tool_name: result},
        "iterations": state["iterations"] + 1,
    }


__all__ = ["tool_executor"]
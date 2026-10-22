import asyncio
import logging
import re

from google import genai
from google.genai import errors, types

from src.config.settings import get_settings
from src.graph.state import AgentState
from src.tools.tool_definitions import TOOL_FUNCTIONS, execute_tool

logger = logging.getLogger("ai_service")
settings = get_settings()
client = genai.Client(api_key=settings.GEMINI_API_KEY)

SYSTEM_PROMPT = """You are an engineering-metrics analyst for ONE repository.
Repository id: {repo_id}. Always use exactly this repo_id in every tool call.
Rules:
- Base every number you state on tool results. Never invent figures.
- If a metric is null, empty, or based on zero deployments or PRs, say there is
  no data for it. Do not treat it as good or bad (0% failure rate with 0
  deployments is NOT 'elite').
- When several tools are needed and independent, call them all in the same step.
- If a tool returns an error, say that data was unavailable and continue with
  what you have.
  - Most number tools default to the last 30 days. If a result is empty, try once more with days=120 before saying there is no data, and always say which time period you checked.
- For questions about WHAT was worked on (topics, kinds of changes), call search_context with a short query such as "recent changes", and mention the PR titles and commit messages it returns.
- Only say there are no pull requests if the number tools AND search_context both returned nothing.
- Call each tool at most once per question. Do not repeat a tool with the same arguments.
"""


def _is_transient(e: errors.APIError) -> bool:
    return getattr(e, "code", None) in (429, 500, 503, 504)


def _retry_delay(e: errors.APIError, attempt: int) -> float:
    match = re.search(r"retry in ([\d.]+)s", str(e))
    return min(float(match.group(1)) + 1, 60) if match else 5 * (attempt + 1)


async def _generate(**kwargs):
    """Call Gemini. Retry transient errors (rate limit / overload), then
    fall back to GEMINI_FALLBACK_MODEL if the primary keeps failing."""
    models = [kwargs.pop("model", settings.GEMINI_MODEL)]
    if settings.GEMINI_FALLBACK_MODEL and settings.GEMINI_FALLBACK_MODEL not in models:
        models.append(settings.GEMINI_FALLBACK_MODEL)

    last_error = None
    for i, model in enumerate(models):
        tries = 3 if i == len(models) - 1 else 2  # fail over sooner if a fallback exists
        for attempt in range(tries):
            try:
                return await client.aio.models.generate_content(model=model, **kwargs)
            except errors.APIError as e:
                if not _is_transient(e):
                    raise  # real errors (bad request, bad model name) should fail loudly
                last_error = e
                wait = _retry_delay(e, attempt)
                logger.warning("%s busy (code %s), attempt %d/%d", model, e.code, attempt + 1, tries)
                if attempt < tries - 1:
                    await asyncio.sleep(wait)
        logger.warning("Giving up on %s", model)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to generate content: all models and retry attempts exhausted")


async def _run_one_tool(name: str, args: dict, repo_id: int) -> dict:
    args = {**args, "repo_id": repo_id}  # never trust the model's repo_id
    for key in ("days", "limit", "repo_id"):
        if key in args:
            args[key] = int(args[key])
    try:
        return await execute_tool(name, args)
    except Exception as e:
        logger.warning("Tool %s failed: %s", name, e)
        return {"error": f"{type(e).__name__}: {e}"}


async def tool_executor(state: AgentState) -> dict:
    response = await _generate(
        model=settings.GEMINI_MODEL,
        contents=state["messages"],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(repo_id=state["repo_id"]),
            tools=TOOL_FUNCTIONS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )

    model_content = response.candidates[0].content
    calls = response.function_calls or []

    if not calls:
        return {
            "messages": state["messages"] + [model_content],
            "final_answer": response.text or "I couldn't produce an answer from the available data.",
            "iterations": state["iterations"] + 1,
        }

    results = await asyncio.gather(
        *[_run_one_tool(c.name, dict(c.args), state["repo_id"]) for c in calls]
    )

    response_parts = [
        types.Part.from_function_response(name=c.name, response={"result": r})
        for c, r in zip(calls, results)
    ]
    return {
        "messages": state["messages"] + [model_content, types.Content(role="user", parts=response_parts)],
        "tools_called": state["tools_called"] + [c.name for c in calls],
        "tool_results": {**state["tool_results"], **{c.name: r for c, r in zip(calls, results)}},
        "iterations": state["iterations"] + 1,
    }
from click import prompt
import json
import logging

from src.config.llm import generate_text
from src.tools import analytics_tool

logger = logging.getLogger("ai_service")


MAX_OPEN_PRS_IN_PROMPT = 10
async def fetch_or_unavailable(label, coroutine):
    """Get one piece of data. If it fails, return 'unavailable' instead of crashing,
    so one broken endpoint doesn't stop the whole digest."""
    try:
        response = await coroutine
    except Exception as error:
        logger.warning("Digest: could not fetch %s: %s", label, error)
        return "unavailable"
    return response.get("data")

async def collect_week_data(repo_id):
    data={}

    data["dora_last_30_days"]=await fetch_or_unavailable(
        "dora",analytics_tool.get_dora(repo_id,days=30)
    )
    data["cycle_time_last_7_days"] = await fetch_or_unavailable(
        "cycle time (7 days)", analytics_tool.get_cycle_time_summary(repo_id, days=7)
    )
    data["cycle_time_last_30_days"] = await fetch_or_unavailable(
        "cycle time (30 days)", analytics_tool.get_cycle_time_summary(repo_id, days=30)
    )
    data["deployments_last_28_days"] = await fetch_or_unavailable(
        "deployments", analytics_tool.get_deployment_frequency(repo_id, days=28)
    )
    data["contributors_last_7_days"] = await fetch_or_unavailable(
        "contributors", analytics_tool.get_contributors(repo_id, days=7)
    )

    open_prs=await fetch_or_unavailable("open Prs",analytics_tool.get_open_prs(repo_id))
    if isinstance(open_prs,list) and len(open_prs)>MAX_OPEN_PRS_IN_PROMPT:
        open_prs=open_prs[:MAX_OPEN_PRS_IN_PROMPT]
    data["open_prs"]=open_prs

    return data


def build_prompt(org_name, repo_name, data):
    # default=str lets json handle values like decimals and dates that it can't write by itself.
    data_text = json.dumps(data, indent=2, default=str)

    prompt = (
        "You are writing the weekly engineering summary email for the team "
        + org_name + ", about the repository " + repo_name + ".\n\n"
        "Rules:\n"
        "- Use ONLY the data below. Never invent numbers.\n"
        "- If a section says 'unavailable', is empty, or is null, say that data was not available.\n"
        "- Zero deployments or zero pull requests means no activity. "
        "Do not call that good or bad performance.\n"
        "- Write plain text only. No markdown symbols such as ** or #.\n"
        "- Keep it to about 150 to 200 words.\n\n"
        "Write these four parts, in this order, each as a short paragraph:\n"
        "1. Overview of the week.\n"
        "2. What went well.\n"
        "3. What needs attention (name stuck pull requests by number if there are any).\n"
        "4. One suggested action for next week.\n\n"
        "DATA:\n" + data_text
    ) 
    return prompt 

async def generate_digest(repo_id,repo_name,org_name):
    data=await collect_week_data(repo_id)
    prompt=build_prompt(org_name,repo_name,data)
    response=await generate_text(prompt)
    subject = "Weekly engineering summary: " + repo_name
    return {"subject": subject, "narrative": response.strip()}
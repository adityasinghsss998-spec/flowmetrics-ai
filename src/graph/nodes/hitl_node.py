from langgraph.types import interrupt
from src.graph.state import AgentState

async def hitl_node(state: AgentState) -> dict:
    """Pauses the graph and waits for a human decision. The dict passed to
    interrupt() is what a reviewer sees; the dict passed back later via
    Command(resume=...) is what `decision` becomes once this node re-runs."""

    proposed_action = {
        "type": "post_pr_comment",  
        "reasoning": f"Requested by: {state['user_question']}",
    }

    decision = interrupt({
        "run_id" : state["run_id"],
        "proposed_action" : proposed_action,
        "repo_id":state["repo_id"]
    })

    if decision.get("approved"):
        return {
            "approval_status": "approved",
            "proposed_action": proposed_action,
            "final_answer": f"Action approved and would now execute: {proposed_action}",
        }

    reason = decision.get("reason") or "rejected by reviewer"
    return {
        "approval_status": "rejected",
        "proposed_action": proposed_action,
        "final_answer": f"Action cancelled: {reason}",
    }   

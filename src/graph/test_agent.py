import asyncio
import uuid
import logging
from src.graph.agent import get_agent_graph
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

async def main():
    run_id = str(uuid.uuid4())
    graph = await get_agent_graph()
    config = {"configurable": {"thread_id": run_id}}

    result = await graph.ainvoke({
        "messages": [], "repo_id": 1, "org_id": 1,
        "user_question": "What is our DORA score?",
        "tools_called": [], "tool_results": {}, "iterations": 0,
        "final_answer": None, "error": None,
        "requires_approval": False, "proposed_action": None,
        "approval_status": None, "run_id": run_id,
    }, config=config)

    print("Tools called:", result["tools_called"])
    print("Answer:", result["final_answer"])


if __name__ == "__main__":
    asyncio.run(main())
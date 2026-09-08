import asyncio

from src.graph.agent import agent_graph


async def main():
    result = await agent_graph.ainvoke({
        "messages": [],
        "repo_id": 1,
        "org_id": 1,
        "user_question": "Why might our cycle time be increasing? Check both the trend and who's contributing.",
        "tools_called": [],
        "tool_results": {},
        "iterations": 0,
        "final_answer": None,
        "error": None,
    })
    print("Tools called:", result["tools_called"])
    print("Answer:", result["final_answer"])


if __name__ == "__main__":
    asyncio.run(main())
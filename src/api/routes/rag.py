from fastapi import APIRouter

from src.rag.retriever import hybrid_search

router = APIRouter()


@router.get("/rag/search")
async def search(repoId: int, q: str, k: int = 5):
    return {"query": q, "results": await hybrid_search(q, repoId, top_k=k)}
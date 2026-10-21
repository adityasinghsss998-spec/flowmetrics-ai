import asyncio
import logging
import re

from rank_bm25 import BM25Okapi

from src.rag.clients import embed_text, get_index
from src.rag.corpus import STATIC_DOCS, load_documents

logger = logging.getLogger("ai_service")
_bm25_cache: dict[int, tuple] = {}  # remembered per repo until the server restarts


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


async def _keyword_search(query: str, repo_id: int, top_k: int) -> list[dict]:
    """Exact-word search (BM25), built from the database."""
    if repo_id not in _bm25_cache:
        docs=STATIC_DOCS + await load_documents(repo_id)
        _bm25_cache[repo_id] = (BM25Okapi([_words(str(d["text"])) for d in docs]),docs)
    
    bm25,docs=_bm25_cache[repo_id]
    scores=bm25.get_scores(_words(query))
    ranked = sorted(zip(docs,scores),key=lambda x : x[1],reverse=True)
    return [{ "id":d["id"],"text":d["text"],"score":float(score)} for d,score in ranked if score>0]

 

    
def _meaning_search_sync(query: str, repo_id: int, top_k: int) -> list[dict]:
    """Search-by-meaning (Pinecone). Includes the shared repo_id 0 documents."""
    result = get_index().query(
        vector=embed_text(query), top_k=top_k,
        filter={"repo_id": {"$in": [repo_id, 0]}}, include_metadata=True,
    )
    return [{"id": m.id, "text": m.metadata.get("text", ""), "score": float(m.score)} for m in result.matches]


def _scale_0_to_1(results: list[dict]) -> dict[str, tuple]:
    """The two searches score on different scales, so squeeze each into 0..1 first."""
    if not results:
        return {}
    low, high = min(r["score"] for r in results), max(r["score"] for r in results)
    scaled_dict={}
    for r in results:
        doc_id=r["id"]
        text=r["text"]
        score=r["score"]

        if high == low:
            scaled_score = 1.0  # Edge case: if all scores are identical, give them all 1.0
        else:
            scaled_score = (score - low) / (high - low)
            
        scaled_dict[doc_id] = (scaled_score, text)
        
    return scaled_dict
 

async def hybrid_search(query: str, repo_id: int, top_k: int = 5) -> list[dict]:
    meaning, keywords = await asyncio.gather( 
        asyncio.to_thread(_meaning_search_sync, query, repo_id, 20),  # runs in a background thread
        _keyword_search(query, repo_id, 20),
        return_exceptions=True,
    )
    meaning_results: list[dict] = []
    if isinstance(meaning, BaseException):
        logger.warning("Meaning search failed, using keywords only: %s", meaning)
    else:
        meaning_results = meaning

    keyword_results: list[dict] = []
    if isinstance(keywords, BaseException):
        logger.warning("Keyword search failed, using meaning only: %s", keywords)
    else:
        keyword_results = keywords

    combined: dict[str, dict] = {}
    for weight, scaled in ((0.6, _scale_0_to_1(meaning_results)), (0.4, _scale_0_to_1(keyword_results))):
        for doc_id, (score, text) in scaled.items():
            entry = combined.setdefault(doc_id, {"text": text, "score": 0.0})
            entry["score"] += weight * score

    best = sorted(combined.values(), key=lambda r: r["score"], reverse=True)[:top_k]
    return [{"text": r["text"], "score": round(r["score"], 3)} for r in best]
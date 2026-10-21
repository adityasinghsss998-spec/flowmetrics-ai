import asyncio
import sys

from src.rag.clients import embed_text, ensure_index
from src.rag.corpus import STATIC_DOCS, load_documents


async def embed_repo(repo_id: int) -> None:
    index = ensure_index()
    docs = STATIC_DOCS + await load_documents(repo_id)
    print(f"Embedding {len(docs)} items for repo {repo_id} (this takes a minute)...")

    vectors = []
    for i, doc in enumerate(docs, 1):
        vectors.append({
            "id": doc["id"],
            "values": embed_text(str(doc["text"])),
            "metadata": {"repo_id": doc["repo_id"], "kind": doc["kind"], "text": doc["text"]},
        })
        if i % 10 == 0:
            print(f"  {i}/{len(docs)}")

    for start in range(0, len(vectors), 100):  # send in batches of 100
        index.upsert(vectors=vectors[start:start + 100])
    print(f"Done. Stored {len(vectors)} items.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(embed_repo(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
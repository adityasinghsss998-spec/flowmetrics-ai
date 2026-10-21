import time
from functools import lru_cache

from google import genai
from google.genai import errors, types
from pinecone import Pinecone, ServerlessSpec

from src.config.settings import get_settings

settings = get_settings()
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768


@lru_cache
def _gemini():
    return genai.Client(api_key=settings.GEMINI_API_KEY)


@lru_cache
def _pinecone():
    return Pinecone(api_key=settings.PINECONE_API_KEY)


def embed_text(text: str) -> list[float]:
    """Turn text into a list of 768 numbers that capture its meaning."""
    for attempt in range(4):
        try:
            result = _gemini().models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            return result.embeddings[0].values
        except errors.APIError as e:
            if getattr(e, "code", None) not in (429, 500, 503) or attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))  # wait and try again

    raise RuntimeError("Failed to generate embedding: retry attempts exhausted")


def ensure_index():
    """Create the Pinecone index the first time, and return a handle to it."""
    pc = _pinecone()
    name = settings.PINECONE_INDEX_NAME
    if not pc.has_index(name):
        pc.create_index(
            name=name, dimension=EMBED_DIM, metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        time.sleep(10)  # give the new index a moment to start
    return pc.Index(host=pc.describe_index(name).host)


@lru_cache
def get_index():
    return ensure_index()
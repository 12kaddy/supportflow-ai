from functools import lru_cache

from app.core.config import get_settings
from app.observability.events import emit
from app.rag.corpus import DEFAULT_ROOT, load_chunks
from app.rag.ranking import fuse_ranks, keyword_rank, tokenize


@lru_cache
def collection():
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_path)
    embedder = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
    return client.get_or_create_collection(
        "support_policy_chunks_v1", embedding_function=embedder, metadata={"hnsw:space": "cosine"}
    )


def ingest(root=DEFAULT_ROOT):
    chunks = load_chunks(root)
    c = collection()
    c.upsert(
        ids=[chunk.id for chunk in chunks],
        documents=[chunk.text for chunk in chunks],
        metadatas=[
            {"source": chunk.source, "version": chunk.version, "document_hash": chunk.document_hash}
            for chunk in chunks
        ],
    )
    stale = set(c.get(include=[])["ids"]) - {chunk.id for chunk in chunks}
    if stale:
        c.delete(ids=sorted(stale))
    return len({chunk.source for chunk in chunks})


def vector_candidates(query, chunks, limit=10):
    try:
        c = collection()
        if c.count() == 0:
            return [], "empty"
        result = c.query(
            query_texts=[query], n_results=min(limit, c.count()), include=["distances"]
        )
        current = {chunk.id for chunk in chunks}
        ids = [
            identifier
            for identifier, distance in zip(result["ids"][0], result["distances"][0])
            if identifier in current and distance <= 0.65
        ]
        return ids, "available"
    except Exception:
        return [], "unavailable"


def search_policy(query: str, limit=3, root=DEFAULT_ROOT, use_vectors=True) -> list[dict]:
    if not 1 <= limit <= 10:
        raise ValueError("Retrieval limit must be between 1 and 10")
    if not tokenize(query):
        return []
    chunks = load_chunks(root)
    keywords = [identifier for identifier, _ in keyword_rank(query, chunks)]
    vectors, vector_status = vector_candidates(query, chunks) if use_vectors else ([], "disabled")
    by_id = {chunk.id: chunk for chunk in chunks}
    results = []
    for identifier, score, methods in fuse_ranks(keywords, vectors, limit):
        chunk = by_id[identifier]
        results.append(
            {
                "text": chunk.text,
                "source": chunk.source,
                "version": chunk.version,
                "chunk_id": chunk.id,
                "document_hash": chunk.document_hash,
                "citation": chunk.citation,
                "rank_score": round(score, 6),
                "retrieval_methods": methods,
                "vector_status": vector_status,
            }
        )
    emit(
        "policy_retrieval_completed",
        result_count=len(results),
        vector_status=vector_status,
        keyword_candidates=len(keywords),
        vector_candidates=len(vectors),
    )
    return results

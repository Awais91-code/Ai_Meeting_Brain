from pathlib import Path
import hashlib

import chromadb

from app.config import settings

# Resolve relative to this file (app/services/), not the process's
# current working directory, so this works the same whether the app
# is launched via `uvicorn app.main:app` from the project root, from
# inside app/, or from a test runner with a different cwd. Can be
# overridden with CHROMA_DB_PATH (tests use this to avoid writing into
# the real project's chroma_db folder).
_DEFAULT_CHROMA_DB_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "chroma_db"
)
CHROMA_DB_PATH = settings.chroma_db_path or _DEFAULT_CHROMA_DB_PATH

client = chromadb.PersistentClient(
    path=CHROMA_DB_PATH
)


collection = client.get_or_create_collection(
    name="meeting_" + hashlib.sha256(f"{settings.embedding_provider}:{'lexical-v2' if settings.embedding_provider == 'local' else settings.embedding_model}".encode()).hexdigest()[:16],
    # IMPORTANT: Chroma defaults to raw L2 (squared Euclidean) distance
    # if this isn't set explicitly. Real embedding vectors are not
    # unit-length, so L2 distances routinely exceed 1.0-2.0 even for a
    # perfect semantic match — which is why every chat question was
    # being rejected as "not found" (the app's relevance threshold was
    # tuned assuming cosine distance, 0-2 range, not L2). Cosine
    # distance is what the rest of the app already assumes.
    #
    # Renamed to "_v2" (rather than reconfiguring in place) because an
    # existing collection's distance metric can't be changed after
    # creation.
    metadata={"hnsw:space": "cosine"},
)

# Any meeting embedded BEFORE this fix has its chunks sitting in the
# old collection (raw L2 metric) instead of the new one. Rather than
# forcing every existing meeting to be manually "Reprocessed" before
# chat works again, search() below falls back to this legacy
# collection when the new one has nothing for a given meeting.
_legacy_collection = client.get_or_create_collection(
    name="meeting_transcripts"
)


def add_chunks(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
):
    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def delete_chunks(meeting_id: int):
    _legacy_collection.delete(where={"meeting_id": meeting_id})
    collection.delete(
        where={
            "meeting_id": meeting_id
        }
    )


def search(
    query_embedding: list[float],
    meeting_id: int,
    n_results: int = 5,
):
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={
            "meeting_id": meeting_id
        },
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0] if results else []

    if documents:
        return results, "cosine"

    # Nothing in the new (cosine) collection for this meeting — check
    # whether it has legacy chunks from before the collection rename.
    if settings.embedding_provider != "openrouter":
        return results, "cosine"

    legacy_results = _legacy_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={
            "meeting_id": meeting_id
        },
        include=["documents", "metadatas", "distances"],
    )

    return legacy_results, "legacy_l2"

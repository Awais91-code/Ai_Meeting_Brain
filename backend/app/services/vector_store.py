import chromadb


client = chromadb.PersistentClient(
    path="./chroma_db"
)


collection = client.get_or_create_collection(
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


def search(
    query_embedding: list[float],
    meeting_id: int,
    n_results: int = 5,
):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where={
            "meeting_id": meeting_id
        },
    )
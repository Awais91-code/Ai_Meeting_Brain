"""SQL is the canonical index; vector search enriches its ranked evidence."""
import math
from collections import Counter
from app.models import TranscriptChunk
from app.services.llm import tokenize
from app.services.transcript import chunk_transcript


def retrieve(db, meeting, question: str, vector_documents=(), limit=8):
    chunks = db.query(TranscriptChunk).filter_by(meeting_id=meeting.id).order_by(TranscriptChunk.chunk_index).all()
    contents = [chunk.content for chunk in chunks] or chunk_transcript(meeting.transcript or "")
    if not contents:
        # Recover legacy text without comparing vectors from incompatible models.
        try:
            from app.services.vector_store import _legacy_collection
            contents = _legacy_collection.get(where={"meeting_id": meeting.id}, include=["documents"])["documents"]
        except Exception:
            contents = []
    if not contents:
        return []
    tokens = [tokenize(content) for content in contents]
    frequencies = Counter(word for words in tokens for word in words)
    query = tokenize(question)
    scores = [sum(math.log(1 + len(contents) / frequencies[word]) for word in query & words)
              for words in tokens]
    for rank, document in enumerate(vector_documents):
        if document in contents:
            scores[contents.index(document)] += 1 / (rank + 1)
    broad = any(term in question.casefold() for term in ("summar", "overview", "action items", "decisions", "خلاصہ", "فیصلے", "सारांश", "निर्णय"))
    order = sorted(range(len(contents)), key=lambda i: scores[i], reverse=True)
    if sum(map(len, contents)) <= 30000:
        selected = list(range(len(contents)))
    elif broad:
        selected = sorted(set(order[:limit // 2] + [round(i * (len(contents)-1) / (limit//2-1)) for i in range(limit//2)]))
    else:
        selected = order[:limit]
    sources, budget = [], 32000
    for index in selected:
        content = contents[index][:budget]
        if not content:
            break
        sources.append({"label": f"Source {len(sources)+1}", "meeting_id": meeting.id,
                        "chunk_index": index, "content": content})
        budget -= len(content)
    return sources

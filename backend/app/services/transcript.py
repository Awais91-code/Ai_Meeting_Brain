def clean_transcript(text: str) -> str:
    """
    Basic transcript cleanup.
    """
    text = text.strip()

    # Remove excessive whitespace
    text = " ".join(text.split())

    return text


def chunk_transcript(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[str]:
    """
    Split transcript into overlapping word-based chunks.
    """

    text = clean_transcript(text)

    if not text:
        return []

    words = text.split()

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size

        chunk = " ".join(words[start:end])
        chunks.append(chunk)

        if end >= len(words):
            break

        start = end - chunk_overlap

    return chunks
"""Offline lexical vectors by default; optional semantic embedding providers."""
import hashlib
import math
import requests
from app.config import settings
from app.services.llm import tokenize


def create_embedding(text: str) -> list[float]:
    provider = settings.embedding_provider
    if provider == "local":
        # Stable lexical features, not semantic AI. SQL ranking also uses exact terms.
        vector = [0.0] * 512
        for word in tokenize(text):
            slot = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % len(vector)
            vector[slot] += 1
        norm = math.sqrt(sum(v * v for v in vector)) or 1
        return [v / norm for v in vector]
    if not settings.embedding_model:
        raise ValueError("Set EMBEDDING_MODEL for a semantic embedding provider")
    if provider == "ollama":
        response = requests.post(settings.ollama_url.rstrip("/") + "/api/embed",
                                 json={"model": settings.embedding_model, "input": text}, timeout=(5, 45))
        response.raise_for_status()
        vector = response.json()["embeddings"][0]
    elif provider == "openrouter":
        response = requests.post("https://openrouter.ai/api/v1/embeddings",
                                 headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                                 json={"model": settings.embedding_model, "input": text}, timeout=(5, 30))
        response.raise_for_status()
        vector = response.json()["data"][0]["embedding"]
    else:
        raise ValueError("Unknown EMBEDDING_PROVIDER")
    if not vector or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector):
        raise ValueError("Invalid embedding response")
    return vector

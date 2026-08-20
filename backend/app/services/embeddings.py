import requests

from app.config import settings


OPENROUTER_API_KEY = settings.openrouter_api_key

MODEL = "nvidia/nemotron-3-embed-1b:free"


def create_embedding(text: str) -> list[float]:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not found")

    response = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "input": text,
            "encoding_format": "float",
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return data["data"][0]["embedding"]
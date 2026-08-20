import requests

from app.config import settings


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def generate_summary(transcript: str) -> str:

    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY not found")

    prompt = f"""
You are an AI assistant that summarizes company meetings.

Create a concise and useful summary of the meeting transcript.

Include:
- Main topics discussed
- Important decisions
- Important deadlines
- Important responsibilities

Do not invent information.
Only use information present in the transcript.

MEETING TRANSCRIPT:
{transcript}
"""

    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=120,
    )

    if response.status_code != 200:
        print("OPENROUTER STATUS:", response.status_code)
        print("OPENROUTER RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()

    if "choices" not in data:
        print("❌ Unexpected OpenRouter response:")
        print(data)
        raise ValueError(
            "OpenRouter response does not contain choices"
        )

    return data["choices"][0]["message"]["content"]
"""Bounded provider calls; local evidence remains usable on provider failure."""
import requests
from app.config import settings


def complete(messages: list[dict], *, json_mode=False, max_tokens=1800) -> str:
    provider = settings.llm_provider
    if provider == "auto":
        provider = "openrouter" if settings.openrouter_api_key else "extractive"
    if provider == "extractive":
        raise RuntimeError("Generative AI is not configured; using transcript excerpts.")
    if provider == "ollama":
        payload = {"model": settings.ollama_model, "messages": messages, "stream": False,
                   "options": {"temperature": 0, "num_ctx": 16384, "num_predict": max_tokens}}
        if json_mode:
            payload["format"] = "json"
        response = requests.post(settings.ollama_url.rstrip("/") + "/api/chat",
                                 json=payload, timeout=(5, 90))
        response.raise_for_status()
        content = response.json()["message"]["content"]
    elif provider == "openrouter":
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is missing")
        payload = {"model": settings.chat_model, "messages": messages,
                   "temperature": 0, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                                 json=payload, timeout=(5, 45))
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    else:
        raise ValueError("LLM_PROVIDER must be auto, ollama, openrouter or extractive")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI provider returned an empty answer")
    return content.strip()

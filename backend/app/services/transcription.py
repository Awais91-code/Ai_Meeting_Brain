"""High-quality local multilingual speech recognition.

The default model is large-v3 because the project is used for English/Urdu/Hindi
meetings.  A local small model is kept as an offline fallback so an interrupted
large-model download never makes an existing installation unusable.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from threading import Lock

from app.config import settings

logger = logging.getLogger(__name__)
_inference_lock = Lock()


def effective_model_name() -> str:
    """Return the quality model used by this patch.

    Older project installs explicitly stored WHISPER_MODEL=small/base in .env.
    Keep those installs upgrade-safe by preferring large-v3 unless the admin
    explicitly disables WHISPER_PREFER_LARGE_V3. Custom model paths/names are
    always respected.
    """
    requested = (settings.whisper_model or "large-v3").strip()
    if settings.whisper_prefer_large_v3 and requested.lower() in {"small", "base"}:
        return "large-v3"
    return requested


def _cache_dir() -> Path:
    path = Path(settings.data_dir) / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_local_model(model_name: str) -> str | None:
    """Return a CTranslate2 snapshot path when the requested model is cached."""
    candidate = Path(model_name)
    if candidate.is_dir() and (candidate / "model.bin").is_file():
        return str(candidate)

    try:
        from faster_whisper.utils import download_model
        from huggingface_hub.errors import LocalEntryNotFoundError

        cached = download_model(
            model_name,
            cache_dir=str(_cache_dir()),
            local_files_only=True,
        )
        if (Path(cached) / "model.bin").is_file():
            return cached
    except (LocalEntryNotFoundError, OSError, ValueError):
        return None
    return None


def _build_model(model_name: str, *, allow_download: bool):
    from faster_whisper import WhisperModel

    local = _resolve_local_model(model_name)
    source = local or model_name
    return WhisperModel(
        source,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        cpu_threads=settings.whisper_cpu_threads,
        download_root=str(_cache_dir()),
        local_files_only=bool(local) or not allow_download,
    )


@lru_cache(maxsize=1)
def whisper_model():
    """Load the configured model, preferring large-v3 and falling back safely.

    large-v3 is downloaded once into DATA_DIR/models when it is not already
    cached. If the machine is offline and the download cannot start, the
    existing multilingual small/base cache can still be used until the stronger
    model is prepared with ``python backend/prepare_models.py``.
    """
    requested = effective_model_name()
    try:
        return _build_model(requested, allow_download=True)
    except Exception as primary_error:
        logger.warning("Could not load Whisper model %s: %s", requested, primary_error)
        for fallback in ("small", "base"):
            if fallback == requested:
                continue
            try:
                model = _build_model(fallback, allow_download=False)
                logger.warning(
                    "Using cached %s model as a temporary fallback. Prepare %s for better accuracy.",
                    fallback,
                    requested,
                )
                return model
            except Exception:
                continue
        raise RuntimeError(
            f"Whisper model '{requested}' is not available. Connect to the internet once and run "
            "'python backend/prepare_models.py', or point WHISPER_MODEL to a local model folder."
        ) from primary_error


def _prompt_for(mode: str, vocabulary: str) -> str:
    vocab = " ".join(vocabulary.split())
    if mode == "ur":
        base = (
            "یہ ایک کمپنی کی میٹنگ ہے۔ اردو گفتگو کو اردو رسم الخط میں درست طور پر لکھیں۔ "
            "English technical terms, product names, people names, acronyms and code words کو "
            "اصل English spelling میں رکھیں۔ بات کا ترجمہ نہ کریں، صرف درست transcription کریں۔"
        )
    elif mode == "hi":
        base = (
            "यह एक कंपनी की मीटिंग है। हिंदी को देवनागरी में सही लिखें और English technical "
            "terms, names, acronyms and code words की original English spelling रखें। Translate न करें।"
        )
    elif mode == "en":
        base = (
            "This is a company meeting. Transcribe exactly, preserving names, acronyms, technical terms, "
            "product names, numbers and action items. Do not translate or summarize."
        )
    else:
        base = (
            "This is a multilingual company meeting that may switch between Urdu, English and Hindi. "
            "Transcribe the spoken language instead of translating it. Use Urdu script for Urdu, "
            "Devanagari for Hindi, and preserve English technical terms, names, acronyms and code words "
            "with their English spelling."
        )

    if vocab:
        return f"{base}\nImportant meeting vocabulary/names: {vocab}"
    return base


def transcribe_audio(path: str, language: str | None = None, vocabulary: str = "") -> str:
    mode = language if language is not None else (settings.whisper_language or "auto")
    mode = (mode or "auto").strip().lower()
    if mode not in {"auto", "en", "ur", "hi"}:
        raise ValueError("Choose mixed/automatic, English, Urdu or Hindi")

    configured = effective_model_name().lower()
    if mode != "en" and configured.endswith(".en"):
        raise ValueError("Urdu/Hindi/mixed audio needs a multilingual model, not an .en model")

    prompt = _prompt_for(mode, vocabulary)

    # Keep the lock while consuming Faster-Whisper's lazy generator. A single
    # large-v3 instance can otherwise exhaust RAM when two meetings finish at once.
    with _inference_lock:
        segments, info = whisper_model().transcribe(
            path,
            task="transcribe",
            language=None if mode == "auto" else mode,
            multilingual=mode == "auto",
            beam_size=settings.whisper_beam_size,
            patience=1.2,
            length_penalty=1.0,
            repetition_penalty=1.05,
            temperature=0.0,
            condition_on_previous_text=True,
            prompt_reset_on_temperature=0.5,
            initial_prompt=prompt,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 450,
                "min_speech_duration_ms": 180,
            },
            word_timestamps=False,
            hotwords=" ".join(vocabulary.split()) or None,
            language_detection_threshold=0.40,
            language_detection_segments=3,
        )

        lines = []
        for segment in segments:
            text = " ".join(segment.text.strip().split())
            if not text:
                continue
            minutes = int(segment.start) // 60
            seconds = int(segment.start) % 60
            lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")

    if not lines:
        raise ValueError(
            "No speech detected. Check the microphone/shared-tab audio, move closer to the microphone, "
            "or upload a clearer recording."
        )

    detected = getattr(info, "language", None)
    probability = getattr(info, "language_probability", None)
    if mode == "auto" and detected and probability is not None:
        logger.info("Whisper detected language %s (%.2f)", detected, probability)

    return "\n".join(lines)

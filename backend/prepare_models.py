"""Download the configured free speech model before the first real meeting."""
from app.config import settings
from app.services.transcription import effective_model_name, whisper_model

if __name__ == "__main__":
    whisper_model()
    print(f"Whisper model '{effective_model_name()}' is ready in DATA_DIR/models.")

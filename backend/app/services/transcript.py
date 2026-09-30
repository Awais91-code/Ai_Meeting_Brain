import re


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?\u061f\u06d4\u0964\u0965])[ \t]+")
SPEAKER_TURN = re.compile(r"^[^:\n]{1,80}:[^\n]+$")


def clean_transcript(text: str) -> str:
    """Clean whitespace while preserving non-empty transcript lines."""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []

    for line in text.split("\n"):
        cleaned_line = line.strip()
        if cleaned_line:
            lines.append(cleaned_line)

    return "\n".join(lines)


def _split_into_units(text: str) -> list[str]:
    """Split plain lines by sentence, while keeping labeled speaker turns whole."""
    units = []

    for line in text.split("\n"):
        if SPEAKER_TURN.match(line):
            # A speaker label must remain attached to the complete turn.
            units.append(line)
            continue

        # Terminal punctuation remains in each unit. This supports English and
        # Urdu sentence endings without requiring an NLP dependency.
        for sentence in SENTENCE_BOUNDARY.split(line):
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)

    return units


def _word_count(text: str) -> int:
    return len(text.split())


def _overlap_units(units: list[str], chunk_overlap: int) -> list[str]:
    """Return complete trailing units up to the requested overlap size."""
    overlap = []
    overlap_words = 0

    for unit in reversed(units):
        unit_words = _word_count(unit)
        if overlap_words + unit_words > chunk_overlap:
            break
        overlap.insert(0, unit)
        overlap_words += unit_words

    return overlap


def chunk_transcript(
    text: str,
    chunk_size: int = 300,
    chunk_overlap: int = 50,
) -> list[str]:
    """Create sentence-aware, overlapping transcript chunks.

    Chunks target 300 words with up to 50 words of whole-unit overlap. A unit
    is either a sentence or a speaker-labelled turn, so a long unit is kept
    complete instead of being silently truncated or split mid-sentence.
    """
    text = clean_transcript(text)
    if not text:
        return []

    units = _split_into_units(text)
    if not units:
        return []

    if chunk_size <= 0 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("Require chunk_size > chunk_overlap >= 0")
    # A pasted paragraph or very long speaker turn must not overflow model input.
    bounded_units = []
    for unit in units:
        words = unit.split()
        if len(words) <= chunk_size:
            bounded_units.append(unit)
        else:
            for start in range(0, len(words), chunk_size - chunk_overlap):
                bounded_units.append(" ".join(words[start:start + chunk_size]))
                if start + chunk_size >= len(words):
                    break
    units = bounded_units

    chunks = []
    current_units = []
    current_words = 0

    for unit in units:
        unit_words = _word_count(unit)

        if not current_units:
            current_units.append(unit)
            current_words = unit_words
            continue

        if current_words + unit_words <= chunk_size:
            current_units.append(unit)
            current_words += unit_words
            continue

        chunks.append(" ".join(current_units))
        current_units = _overlap_units(current_units, min(chunk_overlap, max(0, chunk_size - unit_words)))
        current_units.append(unit)
        current_words = sum(_word_count(item) for item in current_units)

    if current_units:
        chunks.append(" ".join(current_units))

    return chunks

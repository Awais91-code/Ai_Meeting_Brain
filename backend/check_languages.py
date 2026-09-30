"""Opt-in Urdu/Hindi speech check using public Google FLEURS (CC BY 4.0).

Downloads one sample per language, saves references/results under DATA_DIR, and
reports sample word error rates. This is a smoke check, not a benchmark claim.
Source: https://huggingface.co/datasets/google/fleurs
"""
import argparse
import json
import re
import unicodedata
from pathlib import Path

import requests
from app.config import settings
from app.services.transcription import transcribe_audio


def download_sample(config, folder):
    metadata = folder / f"{config}.json"
    audio = folder / f"{config}.audio"
    if not metadata.exists() or not audio.exists():
        # Refresh the reference when its short-lived audio URL has expired.
        for endpoint in ["rows", "first-rows"]:
            params = {"dataset": "google/fleurs", "config": config, "split": "test"}
            if endpoint == "rows":
                params.update(offset=0, length=1)
            response = requests.get("https://datasets-server.huggingface.co/" + endpoint,
                                    params=params, timeout=30)
            if response.ok:
                break
        response.raise_for_status()
        row = response.json()["rows"][0]["row"]
        response = requests.get(row["audio"][0]["src"], timeout=60)
        response.raise_for_status()
        audio.write_bytes(response.content)
        metadata.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    return audio, json.loads(metadata.read_text(encoding="utf-8"))


def words(text):
    text = re.sub(r"\[\d+:\d+\]", "", text)
    return "".join(c if not unicodedata.category(c).startswith("P") else " "
                   for c in unicodedata.normalize("NFC", text).lower()).split()


def word_error_rate(reference, hypothesis):
    ref, hyp = words(reference), words(hypothesis)
    previous = list(range(len(hyp)+1))
    for i, expected in enumerate(ref, 1):
        current = [i]
        for j, actual in enumerate(hyp, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(expected != actual)))
        previous = current
    return previous[-1] / max(1, len(ref))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--language", action="append", choices=["ur", "hi"],
                        help="Check only selected languages (repeat for both).")
    args = parser.parse_args()
    folder = Path(settings.data_dir) / "language-check"
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for config, language, script in [("ur_pk", "ur", r"[\u0600-\u06ff]"), ("hi_in", "hi", r"[\u0900-\u097f]")]:
        if args.language and language not in args.language:
            continue
        audio, row = download_sample(config, folder)
        if args.download_only:
            print(f"Downloaded {config} reference audio", flush=True)
            continue
        transcript = transcribe_audio(str(audio), language=language)
        assert re.search(script, transcript), f"No native-script output for {config}"
        rate = word_error_rate(row["raw_transcription"], transcript)
        results.append({"language":language, "model":settings.whisper_model,
                        "reference":row["raw_transcription"], "transcript":transcript,
                        "sample_word_error_rate":rate,
                        "source":f"google/fleurs, {row.get('sample_split', 'test')} row 0, CC BY 4.0"})
        print(f"PASS: {config} native-script transcription; sample WER {rate:.1%}", flush=True)
        filename = "results-" + Path(settings.whisper_model).name.replace("/", "-") + ".json"
        (folder / filename).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

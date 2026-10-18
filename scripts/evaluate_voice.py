"""Measure local ASR WER on consented recordings; optionally summarize browser turn metrics."""

import argparse
import hashlib
import json
import platform
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from app.core.config import get_settings
from app.voice.audio import LANGUAGES, SAMPLE_RATE
from app.voice.evaluation import summarize, word_errors


def read_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (
            1,
            2,
            SAMPLE_RATE,
        ):
            raise ValueError("Recordings must be mono PCM16 WAV at 16000 Hz")
        if source.getnframes() > 30 * SAMPLE_RATE:
            raise ValueError("Recordings must be at most 30 seconds")
        return source.readframes(source.getnframes())


def measure(manifest, transcribe):
    dataset = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if dataset.get("version") != "voice-wer-v1" or not dataset.get("cases"):
        raise ValueError("Expected a nonempty voice-wer-v1 dataset")
    root = Path(manifest).resolve().parent
    rows = []
    identifiers = set()
    for case in dataset["cases"]:
        if case["language"] not in LANGUAGES or case["id"] in identifiers:
            raise ValueError("Unsupported language or duplicate scenario ID")
        identifiers.add(case["id"])
        word_errors(case["reference"], "")  # Validate references even when audio is missing.
        row = {"id": case["id"], "language": case["language"]}
        try:
            path = (root / case["audio"]).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Audio must remain inside the manifest directory")
            pcm = read_pcm(path)
            started = perf_counter()
            hypothesis = transcribe(pcm, case["language"], threading.Event())
            row.update(
                word_errors(case["reference"], hypothesis),
                hypothesis=hypothesis,
                reference=case["reference"],
                asr_latency_ms=round((perf_counter() - started) * 1000, 2),
                audio_duration_ms=round(len(pcm) / (SAMPLE_RATE * 2) * 1000, 2),
            )
        except Exception as exc:
            row["error_type"] = type(exc).__name__
        rows.append(row)
    return {
        "version": "voice-evaluation-v1",
        "dataset_sha256": hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
        "environment": {"platform": platform.platform(), "processor": platform.processor()},
        "dataset_version": dataset["version"],
        "normalization": "NFC, casefold, punctuation as spaces, whitespace word split; no transliteration",
        "summary": summarize(rows),
        "results": rows,
    }


def turn_summary(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["measurements"]
    summary = {}
    for language in sorted({row["language"] for row in rows}):
        subset = [row for row in rows if row["language"] == language]
        summary[language] = {"completed_turns": len(subset)}
        for metric in ["time_to_first_audio_ms", "asr_latency_ms", "turn_latency_ms"]:
            values = sorted(row[metric] for row in subset if row.get(metric) is not None)
            summary[language][metric] = (
                {
                    "mean": round(sum(values) / len(values), 2),
                    "p50": values[(len(values) - 1) // 2],
                    "p95": values[min(len(values) - 1, int(0.95 * len(values)))],
                }
                if values
                else None
            )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--run-asr", action="store_true", help="Explicitly load local speech models"
    )
    parser.add_argument("--turns", type=Path, help="Optional exported browser measurements")
    parser.add_argument("--output-dir", type=Path, default=Path(".local/evaluations"))
    args = parser.parse_args()
    if not args.run_asr and not args.turns:
        parser.error("Choose --manifest FILE --run-asr and/or --turns FILE")
    report = {"version": "voice-evaluation-v1"}
    if args.run_asr:
        if not args.manifest:
            parser.error("--run-asr requires --manifest")
        # ASR-only benchmark does not require Piper/Indic-Parler configuration.
        from faster_whisper import WhisperModel

        settings = get_settings()
        started = perf_counter()
        model = WhisperModel(
            settings.voice_asr_model,
            device=settings.voice_device,
            compute_type=settings.voice_compute_type,
            local_files_only=settings.voice_offline,
            cpu_threads=2,
        )
        load_ms = (perf_counter() - started) * 1000

        def transcribe(pcm, language, cancelled):
            import numpy as np

            segments, _ = model.transcribe(
                np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768,
                language=language,
                task="transcribe",
                beam_size=5,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            return " ".join(segment.text.strip() for segment in segments)

        report = measure(args.manifest, transcribe)
        report["model"] = settings.voice_asr_model
        report["device"] = settings.voice_device
        report["compute_type"] = settings.voice_compute_type
        report["model_load_ms"] = round(load_ms, 2)
    if args.turns:
        report["turn_summary"] = turn_summary(args.turns)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"voice-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {key: report[key] for key in ("summary", "turn_summary") if key in report}, indent=2
        )
    )
    print(f"Report: {path.resolve()}")
    return int(any(row.get("failed") for row in report.get("summary", {}).values()))


if __name__ == "__main__":
    raise SystemExit(main())

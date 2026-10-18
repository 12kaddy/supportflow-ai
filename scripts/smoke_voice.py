"""Explicit synthetic speech smoke test. Results are NOT human-recording accuracy."""

import argparse
import io
import json
import secrets
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from app.core.config import get_settings
from app.voice.engines import get_engine


def pcm16(wav):
    import numpy as np

    with wave.open(io.BytesIO(wav), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Expected mono PCM16 speech output")
        rate = source.getframerate()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    positions = np.arange(int(len(samples) * 16000 / rate)) * rate / 16000
    return np.interp(positions, np.arange(len(samples)), samples).astype("<i2").tobytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-agent", action="store_true", help="Explicitly allow hosted Groq calls"
    )
    parser.add_argument("--settings", type=Path, default=Path(".local/voice/settings.env"))
    parser.add_argument("--output-dir", type=Path, default=Path(".local/voice-smoke"))
    args = parser.parse_args()
    settings = get_settings()
    # Use the prepared local paths without modifying .env or another running process.
    values = dotenv_values(args.settings)
    settings.voice_asr_model = values["VOICE_ASR_MODEL"]
    settings.voice_piper_models = json.loads(values["VOICE_PIPER_MODELS"])
    settings.voice_tts_backend = "piper"
    settings.voice_offline = True
    settings.voice_device, settings.voice_compute_type = "cpu", "int8"
    engine = get_engine()
    dataset = json.loads(
        Path("data/evaluations/voice/manifest.example.json").read_text(encoding="utf-8")
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recordings = {}
    for case in dataset["cases"]:
        print(f"Synthesizing smoke sample {case['id']}", flush=True)
        pcm = pcm16(engine.synthesize(case["reference"], case["language"], threading.Event()))
        recordings[case["id"]] = pcm
        with wave.open(str(args.output_dir / case["audio"]), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(pcm)
    manifest = args.output_dir / "manifest.json"
    manifest.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    from scripts.evaluate_voice import measure

    report = measure(manifest, engine.transcribe)
    report.update(
        dataset_source="synthetic_piper_smoke_not_human_speech", model=settings.voice_asr_model
    )
    if args.live_agent:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from langgraph.checkpoint.memory import InMemorySaver

        from app.api.v1.voice import router

        settings.voice_enabled = True
        settings.auth_mode = "demo"
        settings.email_enabled = False
        settings.api_key = secrets.token_urlsafe(32)
        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.state.checkpointer = InMemorySaver()
        rows = []
        with TestClient(app) as client:
            for case in dataset["cases"]:
                print(f"Measuring live synthetic channel turn {case['id']}", flush=True)
                with client.websocket_connect("/v1/voice") as socket:
                    socket.send_json(
                        {
                            "type": "start",
                            "language": case["language"],
                            "thread_id": secrets.token_hex(8),
                            "customer_id": "voice-smoke-" + secrets.token_hex(8),
                            "api_key": settings.api_key,
                        }
                    )
                    while True:
                        event = socket.receive_json()
                        if event["type"] == "error":
                            raise RuntimeError(event["message"])
                        if event["type"] == "ready":
                            break
                    pcm = recordings[case["id"]] + bytes(32000)
                    pcm += bytes((-len(pcm)) % 1024)
                    started = time.perf_counter()
                    for index in range(0, len(pcm), 1024):
                        socket.send_bytes(pcm[index : index + 1024])
                        delay = started + ((index + 1024) / 32000) - time.perf_counter()
                        if delay > 0:
                            time.sleep(delay)
                    keep_sending = threading.Event()

                    def silence():
                        while not keep_sending.wait(0.032):
                            try:
                                socket.send_bytes(bytes(1024))
                            except Exception:
                                break

                    sender = threading.Thread(target=silence, daemon=True)
                    sender.start()
                    try:
                        while True:
                            event = socket.receive_json()
                            if event["type"] == "error":
                                rows.append(
                                    {
                                        "id": case["id"],
                                        "language": case["language"],
                                        "error": event["message"],
                                    }
                                )
                                break
                            if event["type"] == "turn_complete":
                                rows.append(
                                    {
                                        "id": case["id"],
                                        "language": case["language"],
                                        **event["metrics"],
                                    }
                                )
                                break
                    finally:
                        keep_sending.set()
                        sender.join(timeout=1)
                    socket.send_json({"type": "stop"})
        report["measurements"] = rows
        report["channel_boundary"] = (
            "In-process WebSocket, real VAD/ASR/Groq/TTS; no microphone, browser playback or network transit"
        )
    path = args.output_dir / f"smoke-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Synthetic-only smoke report: {path.resolve()}")
    return int(
        any(row["failed"] for row in report["summary"].values())
        or any("error" in row for row in report.get("measurements", []))
    )


if __name__ == "__main__":
    raise SystemExit(main())

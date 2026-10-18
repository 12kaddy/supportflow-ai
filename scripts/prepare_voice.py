"""Download the lightweight English/Hindi speech profile into ignored local storage."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--asr-model", default="small", choices=["tiny", "base", "small", "medium", "large-v3"]
    )
    parser.add_argument("--output-dir", type=Path, default=Path(".local/voice"))
    args = parser.parse_args()
    from faster_whisper.utils import download_model
    from piper.download_voices import download_voice

    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    asr_path = root / f"asr-{args.asr_model}"
    print(f"Preparing ASR model: {args.asr_model}")
    download_model(args.asr_model, output_dir=str(asr_path))
    models = {}
    for language, voice in [("en", "en_US-lessac-medium"), ("hi", "hi_IN-pratham-medium")]:
        print(f"Preparing Piper voice: {voice}")
        download_voice(voice, root)
        models[language] = (root / f"{voice}.onnx").as_posix()
    config = (
        "VOICE_ENABLED=true\n"
        f"VOICE_ASR_MODEL={asr_path.as_posix()}\n"
        "VOICE_DEVICE=cpu\nVOICE_COMPUTE_TYPE=int8\nVOICE_OFFLINE=true\n"
        "VOICE_TTS_BACKEND=piper\n"
        f"VOICE_PIPER_MODELS='{json.dumps(models)}'\n"
    )
    target = root / "settings.env"
    target.write_text(config, encoding="utf-8")
    print(f"Prepared. Merge the settings from {target} into .env, then restart the API.")


if __name__ == "__main__":
    main()

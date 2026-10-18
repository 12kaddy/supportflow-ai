"""Lazy local-model adapters. No optional speech imports on normal API startup."""

import asyncio
import io
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.voice.audio import LANGUAGES, SAMPLE_RATE, VoiceError

# Cancelled native inference may finish in the background. Bound both running work
# and the queue; never spawn a new inference thread for every incoming audio frame.
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="supportflow-speech")
_slots = threading.BoundedSemaphore(4)
_load_lock = threading.Lock()


async def blocking(function, *args):
    if not _slots.acquire(blocking=False):
        raise VoiceError("Speech workers are busy. Please try again shortly.")
    try:
        future = _pool.submit(function, *args)
    except BaseException:
        _slots.release()
        raise
    future.add_done_callback(lambda _: _slots.release())
    return await asyncio.wrap_future(future)


def output_languages():
    settings = get_settings()
    if settings.voice_tts_backend == "indic_parler":
        return list(LANGUAGES)
    return [code for code in LANGUAGES if settings.voice_piper_models.get(code)]


class SileroDetector:
    def __init__(self):
        from silero_vad import load_silero_vad

        self.model = load_silero_vad(onnx=True)

    def probability(self, pcm):
        import numpy as np
        import torch

        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        return float(self.model(torch.from_numpy(samples), SAMPLE_RATE).item())


class SpeechEngine:
    def __init__(self):
        from faster_whisper import WhisperModel

        settings = get_settings()
        self.lock = threading.Lock()
        self.asr = WhisperModel(
            settings.voice_asr_model,
            device=settings.voice_device,
            compute_type=settings.voice_compute_type,
            local_files_only=settings.voice_offline,
            cpu_threads=2,
        )
        self.voices = {}
        self.indic = None
        if settings.voice_tts_backend == "indic_parler":
            self.indic = IndicParler()
        else:
            from piper import PiperVoice

            for language in output_languages():
                path = Path(settings.voice_piper_models[language])
                if not path.is_file() or not Path(str(path) + ".json").is_file():
                    raise VoiceError("A configured Piper voice or its .onnx.json file is missing.")
                self.voices[language] = PiperVoice.load(str(path))

    def transcribe(self, pcm, language, cancelled):
        import numpy as np

        with self.lock:
            if cancelled.is_set():
                return ""
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            segments, _ = self.asr.transcribe(
                samples,
                language=language,
                task="transcribe",
                beam_size=5,
                condition_on_previous_text=False,
                vad_filter=False,  # Live channel has already segmented using Silero.
            )
            parts = []
            for segment in segments:
                if cancelled.is_set():
                    break
                parts.append(segment.text.strip())
            text = " ".join(parts).strip()
            return "" if cancelled.is_set() else text

    def synthesize(self, text, language, cancelled):
        with self.lock:
            if cancelled.is_set():
                return b""
            if self.indic:
                audio = self.indic.synthesize(text, cancelled)
            else:
                voice = self.voices.get(language)
                if voice is None:
                    raise VoiceError("No speech output voice is configured for this language.")
                stream = io.BytesIO()
                with wave.open(stream, "wb") as output:
                    voice.synthesize_wav(text, output)
                audio = stream.getvalue()
            return b"" if cancelled.is_set() else audio


class IndicParler:
    """Optional larger adapter, installed separately after model-access acceptance."""

    def __init__(self):
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        settings = get_settings()
        self.device = settings.voice_device
        kwargs = {"local_files_only": settings.voice_offline}
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(
            settings.voice_indic_model, **kwargs
        ).to(self.device)
        self.model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(settings.voice_indic_model, **kwargs)
        self.description_tokenizer = AutoTokenizer.from_pretrained(
            self.model.config.text_encoder._name_or_path, **kwargs
        )

    def synthesize(self, text, cancelled):
        import numpy as np
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class Interrupted(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return cancelled.is_set()

        description = self.description_tokenizer(
            "A clear speaker delivers speech at a moderate pace with very clear audio.",
            return_tensors="pt",
        ).to(self.device)
        prompt = self.tokenizer(text, return_tensors="pt").to(self.device)
        with torch.inference_mode():
            generated = self.model.generate(
                input_ids=description.input_ids,
                attention_mask=description.attention_mask,
                prompt_input_ids=prompt.input_ids,
                prompt_attention_mask=prompt.attention_mask,
                stopping_criteria=StoppingCriteriaList([Interrupted()]),
                max_new_tokens=2048,
            )
        samples = generated.detach().cpu().numpy().squeeze()
        stream = io.BytesIO()
        with wave.open(stream, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.model.config.sampling_rate)
            output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        return stream.getvalue()


@lru_cache(maxsize=1)
def _cached_engine():
    return SpeechEngine()


def get_engine():
    with _load_lock:
        return _cached_engine()


def prepare_session():
    try:
        return get_engine(), SileroDetector()
    except VoiceError:
        raise
    except Exception:
        raise VoiceError(
            "Speech models are unavailable. Install the voice extras and prepare local models."
        ) from None

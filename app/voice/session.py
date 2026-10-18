"""Cancellable turns reuse the production graph, tools, auth, and checkpoints."""

import asyncio
import base64
import re
import threading
from time import perf_counter

from app.agents.graph import build_graph
from app.observability.events import emit
from app.services.chat_runtime import ChatProviderError, invoke_chat
from app.voice.audio import LANGUAGES, SAMPLE_RATE, VoiceError
from app.voice.engines import blocking


def speech_chunks(text, limit=240):
    """Bound synthesis work per chunk; preserve the text rather than dropping a suffix."""
    text = re.sub(r"[*`#]", "", text).strip()
    for sentence in re.split(r"(?<=[.!?।])\s+|\n+", text):
        while sentence:
            end = min(limit, len(sentence))
            if end < len(sentence):
                boundary = sentence.rfind(" ", 0, end)
                if boundary > limit // 2:
                    end = boundary
            yield sentence[:end].strip()
            sentence = sentence[end:].strip()


class VoiceSession:
    def __init__(self, websocket, engine, customer_id, email, thread_id, language):
        self.websocket = websocket
        self.engine = engine
        self.customer_id = customer_id
        self.email = email
        self.thread = f"{customer_id}:{thread_id}"
        self.language = language
        self.task = None
        self.cancelled = threading.Event()
        self.turn_id = 0
        self.send_lock = asyncio.Lock()

    async def send(self, kind, **data):
        async with self.send_lock:
            await asyncio.wait_for(self.websocket.send_json({"type": kind, **data}), timeout=5)

    async def interrupt(self):
        self.cancelled.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        # Also stop audio queued in the browser after server generation has ended.
        await self.send("interrupted", turn_id=self.turn_id)

    async def close(self):
        self.cancelled.set()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def start_turn(self, pcm, speech_ended_at):
        await self.interrupt()
        self.turn_id += 1
        self.cancelled = threading.Event()
        self.task = asyncio.create_task(
            self.bounded_turn(pcm, speech_ended_at, self.turn_id, self.cancelled)
        )

    async def bounded_turn(self, pcm, speech_ended_at, turn_id, cancelled):
        try:
            async with asyncio.timeout(180):
                await self.run_turn(pcm, speech_ended_at, turn_id, cancelled)
        except TimeoutError:
            cancelled.set()
            await self.send(
                "error", turn_id=turn_id, message="Voice turn timed out. Try a shorter request."
            )

    async def run_turn(self, pcm, speech_ended_at, turn_id, cancelled):
        started = perf_counter()
        metrics = {
            "input_audio_ms": round(len(pcm) / (2 * SAMPLE_RATE) * 1000, 2),
            "endpointing_latency_ms": round((started - speech_ended_at) * 1000, 2),
            "time_to_first_audio_ms": None,
        }
        outcome = "error"
        try:
            await self.send("processing", turn_id=turn_id)
            stage = perf_counter()
            transcript = await blocking(self.engine.transcribe, pcm, self.language, cancelled)
            metrics["asr_latency_ms"] = round((perf_counter() - stage) * 1000, 2)
            if not transcript:
                raise VoiceError("No clear speech recognized. Please try again.")
            if len(transcript) > 4000:
                raise VoiceError("Please use a shorter spoken request.")
            await self.send("transcript", turn_id=turn_id, text=transcript)
            stage = perf_counter()
            graph = build_graph(
                self.customer_id,
                self.websocket.app.state.checkpointer,
                self.email,
                response_language=LANGUAGES[self.language],
            )
            result = await invoke_chat(graph, transcript, self.thread, language=self.language)
            metrics["agent_latency_ms"] = round((perf_counter() - stage) * 1000, 2)
            answer = str(result["messages"][-1].content)
            await self.send("answer", turn_id=turn_id, text=answer)
            if not answer.strip() or len(answer) > 12000:
                raise VoiceError(
                    "The text response is available, but it cannot be spoken in this turn."
                )
            tts_ms = 0
            for index, text in enumerate(speech_chunks(answer)):
                if cancelled.is_set():
                    raise asyncio.CancelledError()
                stage = perf_counter()
                audio = await blocking(self.engine.synthesize, text, self.language, cancelled)
                tts_ms += (perf_counter() - stage) * 1000
                if not audio or cancelled.is_set():
                    raise asyncio.CancelledError()
                if len(audio) > 4_000_000:
                    raise VoiceError("Speech output exceeded the chunk size limit.")
                await self.send(
                    "audio",
                    turn_id=turn_id,
                    index=index,
                    format="wav",
                    data=base64.b64encode(audio).decode("ascii"),
                )
                if metrics["time_to_first_audio_ms"] is None:
                    metrics["time_to_first_audio_ms"] = round(
                        (perf_counter() - speech_ended_at) * 1000, 2
                    )
            metrics["tts_latency_ms"] = round(tts_ms, 2)
            metrics["turn_latency_ms"] = round((perf_counter() - speech_ended_at) * 1000, 2)
            await self.send("turn_complete", turn_id=turn_id, metrics=metrics)
            outcome = "success"
        except asyncio.CancelledError:
            outcome = "interrupted"
            raise
        except (VoiceError, ChatProviderError) as exc:
            await self.send("error", turn_id=turn_id, message=str(exc))
        except Exception as exc:
            emit("voice_turn_failed", error_type=type(exc).__name__)
            await self.send("error", turn_id=turn_id, message="Voice processing failed. Try again.")
        finally:
            emit("voice_turn_completed", outcome=outcome, language=self.language, **metrics)

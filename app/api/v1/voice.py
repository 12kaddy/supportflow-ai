"""Authenticated, bounded PCM WebSocket and a same-origin microphone client."""

import asyncio
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.core.customer_contact import customer_email
from app.core.security import identity
from app.observability.events import emit
from app.voice.audio import FRAME_BYTES, LANGUAGES, Segmenter, VoiceError
from app.voice.engines import blocking, output_languages, prepare_session
from app.voice.session import VoiceSession

router = APIRouter()
WEB = Path(__file__).resolve().parents[2] / "voice/web"
_budget_lock = threading.Lock()
_connections = 0


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["start"]
    thread_id: str = Field(min_length=1, max_length=100)
    language: Literal["en", "hi", "mr", "ta", "te"]
    authorization: str = Field(default="", max_length=16400)
    api_key: str = Field(default="", max_length=1000)
    customer_id: str = Field(default="", max_length=40)


def authenticate(start):
    subject = identity(
        x_api_key=start.api_key,
        x_customer_id=start.customer_id,
        authorization=start.authorization,
    )
    return subject, customer_email(subject, start.authorization)


@contextmanager
def connection_slot():
    global _connections
    with _budget_lock:
        if _connections >= get_settings().voice_max_connections:
            raise VoiceError("Voice connection limit reached. Try again shortly.")
        _connections += 1
    try:
        yield
    finally:
        with _budget_lock:
            _connections -= 1


@router.get("/voice", include_in_schema=False)
async def voice_page():
    return FileResponse(WEB / "voice.html", headers={"Cache-Control": "no-store"})


@router.get("/voice/client.js", include_in_schema=False)
async def voice_client():
    return FileResponse(WEB / "client.js", media_type="text/javascript")


@router.get("/voice/capture.js", include_in_schema=False)
async def voice_capture():
    return FileResponse(WEB / "capture.js", media_type="text/javascript")


@router.get("/voice/config")
async def voice_config():
    settings = get_settings()
    return {
        "enabled": settings.voice_enabled,
        "auth_mode": settings.auth_mode,
        "languages": {code: LANGUAGES[code] for code in output_languages()},
    }


async def receive(websocket, timeout):
    message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect()
    text = message.get("text")
    if text is not None and len(text) > 20000:
        raise VoiceError("Control message is too large.")
    if message.get("bytes") is not None and len(message["bytes"]) != FRAME_BYTES:
        raise VoiceError("Invalid audio frame size.")
    return message


@router.websocket("/voice")
async def voice_socket(websocket: WebSocket):
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if not settings.voice_enabled or (
        origin is not None and origin not in settings.voice_allowed_origins
    ):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session = None
    try:
        with connection_slot():
            message = await receive(websocket, 10)
            start = Start.model_validate_json(message.get("text") or "{}")
            subject, email = await asyncio.to_thread(authenticate, start)
            if start.language not in output_languages():
                raise VoiceError("Configure a speech output voice for the selected language first.")
            await websocket.send_json({"type": "loading"})
            engine, detector = await asyncio.wait_for(blocking(prepare_session), timeout=180)
            session = VoiceSession(
                websocket, engine, subject, email, start.thread_id, start.language
            )
            await session.send("ready", sample_rate=16000, frame_samples=512)
            segmenter = Segmenter()
            deadline = perf_counter() + 900
            last_speech = perf_counter()
            frames = 0
            connected = perf_counter()
            while perf_counter() < deadline:
                message = await receive(websocket, min(30, max(0.01, deadline - perf_counter())))
                if message.get("bytes") is not None:
                    frames += 1
                    # Allow a small network burst, not unlimited pre-recorded audio flooding.
                    if frames * 0.032 > perf_counter() - connected + 3:
                        raise VoiceError("Audio is arriving faster than real time.")
                    frame = message["bytes"]
                    received_at = perf_counter()
                    probability = await asyncio.to_thread(detector.probability, frame)
                    if probability >= 0.6:
                        last_speech = received_at
                    began, audio = segmenter.feed(frame, probability)
                    if began:
                        await session.interrupt()
                        await session.send("speech_start")
                    if audio:
                        # Revalidate expiry/permissions before every agent invocation.
                        await asyncio.to_thread(authenticate, start)
                        await session.start_turn(audio, last_speech)
                else:
                    control = json.loads(message.get("text") or "{}")
                    if not isinstance(control, dict):
                        raise VoiceError("Expected a control object.")
                    if control.get("type") == "interrupt":
                        segmenter.flush()
                        await session.interrupt()
                    elif control.get("type") == "stop":
                        break
                    else:
                        raise VoiceError("Unknown voice control message.")
            await websocket.close(code=1000)
    except WebSocketDisconnect:
        pass
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "message": str(exc.detail)})
        await websocket.close(code=1008)
    except (ValidationError, json.JSONDecodeError):
        await websocket.send_json({"type": "error", "message": "Invalid voice protocol message."})
        await websocket.close(code=1008)
    except (VoiceError, TimeoutError) as exc:
        await websocket.send_json(
            {"type": "error", "message": str(exc) or "Voice connection timed out. Reconnect."}
        )
        await websocket.close(code=1008)
    except Exception as exc:
        emit("voice_connection_failed", error_type=type(exc).__name__)
        try:
            await websocket.send_json({"type": "error", "message": "Voice service is unavailable."})
            await websocket.close(code=1011)
        except (WebSocketDisconnect, RuntimeError):
            pass
    finally:
        if session:
            await session.close()

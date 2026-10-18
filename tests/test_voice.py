"""Voice protocol, cancellation, real customer tools and honest metric accounting."""

import asyncio
import io
import json
import threading
import wave
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from starlette.websockets import WebSocketDisconnect

from app.agents.graph import SYSTEM_PROMPT
from app.api.v1 import routes
from app.api.v1 import voice as api
from app.core.config import get_settings
from app.tools import customer_tools
from app.voice import session as runtime
from app.voice.audio import FRAME_BYTES, Segmenter
from app.voice.evaluation import word_errors
from scripts.evaluate_voice import measure, turn_summary
from tests.test_customer_case_tools import ScriptedToolModel

SPEECH = b"\x10\x01" * 512
SILENCE = bytes(FRAME_BYTES)
START = {
    "type": "start",
    "thread_id": "voice-test",
    "language": "hi",
    "api_key": "customer-secret",
    "customer_id": "alice",
}


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(bytes(320))
    return stream.getvalue()


class FakeSpeech:
    def transcribe(self, pcm, language, cancelled):
        return "मेरा ऑर्डर कहाँ है"

    def synthesize(self, text, language, cancelled):
        return wav_bytes()


@pytest.fixture
def voice_app(setup, monkeypatch):
    app, engine = setup
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_enabled", True)
    monkeypatch.setattr(settings, "voice_tts_backend", "piper")
    monkeypatch.setattr(settings, "voice_piper_models", {"hi": "fake", "en": "fake"})
    monkeypatch.setattr(settings, "voice_allowed_origins", ["http://localhost:8000"])
    monkeypatch.setattr(
        api,
        "prepare_session",
        lambda: (FakeSpeech(), SimpleNamespace(probability=lambda pcm: float(pcm == SPEECH))),
    )
    app.state.checkpointer = InMemorySaver()
    monkeypatch.setattr(customer_tools, "SessionLocal", routes.SessionLocal)
    return app


def connect(client, start=None):
    connection = client.websocket_connect("/v1/voice", headers={"origin": "http://localhost:8000"})
    return connection


def begin(socket, start=None):
    socket.send_json(start or START)
    assert socket.receive_json()["type"] == "loading"
    assert socket.receive_json()["type"] == "ready"


def utterance(socket):
    for _ in range(10):
        socket.send_bytes(SPEECH)
    for _ in range(20):
        socket.send_bytes(SILENCE)


def until(socket, kind):
    events = []
    for _ in range(100):
        event = socket.receive_json()
        events.append(event)
        if event["type"] == kind:
            return events
    raise AssertionError(f"Did not receive {kind}")


def test_voice_reuses_real_graph_tools_and_namespaced_memory(voice_app, monkeypatch):
    received = []

    def graph(subject, checkpointer, email, *, response_language):
        received.append((subject, response_language))
        return create_react_agent(
            ScriptedToolModel(tool_name="lookup_order", tool_args={"order_id": "order"}),
            tools=customer_tools.make_tools(subject),
            prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )

    monkeypatch.setattr(runtime, "build_graph", graph)
    with TestClient(voice_app) as client, connect(client) as socket:
        begin(socket)
        utterance(socket)
        events = until(socket, "turn_complete")
        assert received == [("alice", "Hindi")]
        answer = next(event["text"] for event in events if event["type"] == "answer")
        assert json.loads(answer)["id"] == "order"
        assert any(event["type"] == "audio" for event in events)
        metrics = events[-1]["metrics"]
        assert metrics["time_to_first_audio_ms"] >= metrics["asr_latency_ms"] >= 0
        assert metrics["turn_latency_ms"] >= metrics["time_to_first_audio_ms"]
        assert metrics["endpointing_latency_ms"] >= 0
        socket.send_json({"type": "stop"})
    state = voice_app.state.checkpointer.get({"configurable": {"thread_id": "alice:voice-test"}})
    assert state is not None
    assert (
        voice_app.state.checkpointer.get({"configurable": {"thread_id": "bob:voice-test"}}) is None
    )


def test_speech_barge_in_cancels_pending_agent(voice_app, monkeypatch):
    cancelled = threading.Event()
    monkeypatch.setattr(runtime, "build_graph", lambda *args, **kwargs: object())

    async def slow(*args):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(runtime, "invoke_chat", slow)
    with TestClient(voice_app) as client, connect(client) as socket:
        begin(socket)
        utterance(socket)
        until(socket, "transcript")
        for _ in range(3):
            socket.send_bytes(SPEECH)
        events = until(socket, "speech_start")
        assert any(event["type"] == "interrupted" and event["turn_id"] == 1 for event in events)
        assert cancelled.wait(2)
        assert not any(event["type"] in {"answer", "audio"} for event in events)
        socket.send_json({"type": "stop"})


@pytest.mark.parametrize(
    "start",
    [
        {**START, "api_key": "wrong"},
        {**START, "customer_id": ""},
        {**START, "language": "unknown"},
        {**START, "role": "reviewer"},
    ],
)
def test_bad_identity_or_protocol_never_loads_models(voice_app, monkeypatch, start):
    def forbidden():
        raise AssertionError("Unauthenticated connection loaded models")

    monkeypatch.setattr(api, "prepare_session", forbidden)
    with TestClient(voice_app) as client, connect(client) as socket:
        socket.send_json(start)
        assert socket.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


def test_oidc_reviewer_denied_customer_voice(voice_app, signer, monkeypatch):
    monkeypatch.setattr(api, "prepare_session", lambda: pytest.fail("Reviewer loaded models"))
    with TestClient(voice_app) as client, connect(client) as socket:
        socket.send_json({**START, "authorization": "Bearer " + signer("reviewer", ["reviewer"])})
        assert socket.receive_json()["type"] == "error"


@pytest.mark.parametrize("payload", [b"wrong-size", "[]", '{"type":"unsupported"}'])
def test_malformed_frames_close_channel(voice_app, payload):
    with TestClient(voice_app) as client, connect(client) as socket:
        begin(socket)
        if isinstance(payload, bytes):
            socket.send_bytes(payload)
        else:
            socket.send_text(payload)
        assert socket.receive_json()["type"] == "error"


def test_origin_disabled_and_connection_limit(voice_app, monkeypatch):
    with TestClient(voice_app) as client:
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/v1/voice", headers={"origin": "https://untrusted.example"}),
        ):
            pass
        monkeypatch.setattr(get_settings(), "voice_max_connections", 1)
        with connect(client) as first:
            begin(first)
            with connect(client) as second:
                assert second.receive_json()["type"] == "error"
            first.send_json({"type": "stop"})
        monkeypatch.setattr(get_settings(), "voice_enabled", False)
        with pytest.raises(WebSocketDisconnect), connect(client):
            pass


def test_voice_page_and_assets_do_not_embed_credentials(voice_app):
    with TestClient(voice_app) as client:
        for path in ["/v1/voice", "/v1/voice/client.js", "/v1/voice/capture.js"]:
            response = client.get(path)
            assert response.status_code == 200
            assert "customer-secret" not in response.text
        assert client.get("/v1/voice/config").json()["languages"] == {
            "en": "English",
            "hi": "Hindi",
        }


def test_interrupt_during_tts_discards_native_result(voice_app, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class SlowSpeech(FakeSpeech):
        calls = 0

        def synthesize(self, text, language, cancelled):
            self.calls += 1
            if self.calls == 2:
                entered.set()
                release.wait(3)
            return wav_bytes()

    speech = SlowSpeech()
    monkeypatch.setattr(
        api,
        "prepare_session",
        lambda: (speech, SimpleNamespace(probability=lambda pcm: float(pcm == SPEECH))),
    )
    monkeypatch.setattr(runtime, "build_graph", lambda *args, **kwargs: object())

    async def answer(*args):
        return {"messages": [SimpleNamespace(content="First sentence. Second sentence.")]}

    monkeypatch.setattr(runtime, "invoke_chat", answer)
    try:
        with TestClient(voice_app) as client, connect(client) as socket:
            begin(socket)
            utterance(socket)
            until(socket, "audio")
            assert entered.wait(2)
            socket.send_json({"type": "interrupt"})
            events = until(socket, "interrupted")
            assert not any(event["type"] in {"audio", "turn_complete"} for event in events)
            release.set()
            socket.send_json({"type": "stop"})
    finally:
        release.set()


def test_expired_session_is_revalidated_before_agent_turn(voice_app, monkeypatch):
    from fastapi import HTTPException

    original = api.authenticate
    calls = []

    def authenticate(start):
        calls.append(True)
        if len(calls) > 1:
            raise HTTPException(401, "Please log in again")
        return original(start)

    monkeypatch.setattr(api, "authenticate", authenticate)
    monkeypatch.setattr(
        runtime, "build_graph", lambda *args, **kwargs: pytest.fail("Expired token reached agent")
    )
    with TestClient(voice_app) as client, connect(client) as socket:
        begin(socket)
        utterance(socket)
        events = until(socket, "error")
        assert events[-1]["message"] == "Please log in again"


def test_unsupported_output_language_rejected_before_models(voice_app, monkeypatch):
    monkeypatch.setattr(api, "prepare_session", lambda: pytest.fail("Missing voice loaded models"))
    with TestClient(voice_app) as client, connect(client) as socket:
        socket.send_json({**START, "language": "ta"})
        assert socket.receive_json()["type"] == "error"


def test_segmenter_rejects_noise_and_caps_long_speech():
    segmenter = Segmenter()
    for _ in range(2):
        assert segmenter.feed(SPEECH, 0.9) == (False, None)
    assert segmenter.feed(SILENCE, 0.0) == (False, None)
    segmenter = Segmenter()
    for index in range(1000):
        began, audio = segmenter.feed(SPEECH, 0.9)
        if audio:
            assert len(audio) <= 30 * 16000 * 2
            assert index < 1000
            break
    else:
        pytest.fail("Unbounded audio buffer")


def test_wer_and_failed_recordings_are_not_fake_perfect_scores(tmp_path):
    assert word_errors("मेरा ऑर्डर कहाँ है।", "मेरा ऑर्डर कहाँ है")["errors"] == 0
    assert word_errors("my order is late", "my order late")["errors"] == 1
    assert word_errors("order", "order is late")["errors"] == 2
    (tmp_path / "en.wav").write_bytes(wav_bytes())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "voice-wer-v1",
                "cases": [
                    {
                        "id": "en",
                        "language": "en",
                        "audio": "en.wav",
                        "reference": "my order is late",
                    },
                    {"id": "hi", "language": "hi", "audio": "missing.wav", "reference": "मेरा ऑर्डर"},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = measure(manifest, lambda *args: "my order late")
    assert result["summary"]["en"]["wer"] == 0.25
    assert result["summary"]["hi"]["wer"] is None
    assert result["summary"]["hi"]["failed"] == 1
    assert result["results"][1]["error_type"] == "FileNotFoundError"
    turns = tmp_path / "turns.json"
    turns.write_text(
        json.dumps(
            {
                "measurements": [
                    {
                        "language": "hi",
                        "asr_latency_ms": 20,
                        "turn_latency_ms": 100,
                        "time_to_first_audio_ms": 50,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert turn_summary(turns)["hi"]["time_to_first_audio_ms"]["mean"] == 50

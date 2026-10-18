# Voice support: implementation, setup, and measurement

Measured initial results and their limits are in [voice validation](voice-validation.md).

The voice channel uses faster-whisper for multilingual ASR, per-connection Silero
VAD, the existing LangGraph customer agent/tools/checkpointer, and local speech
synthesis. No second agent or reviewer tool is introduced. The browser captures
the microphone and plays server-generated audio; browser speech recognition and
browser speech synthesis are not used.

## Architecture

```text
Microphone → AudioWorklet → PCM16 / WebSocket → Silero endpointing
 → faster-whisper transcript → existing customer LangGraph and tools
 → final answer → sentence-sized Piper / Indic-Parler synthesis
 → WAV chunks over WebSocket → browser audio queue
```

`app/voice/audio.py` owns wire constants and segmentation; `engines.py` owns model
adapters and bounded native work; `session.py` owns cancellable agent turns.
`app/api/v1/voice.py` owns authentication, protocol, limits and static client
delivery. `app/voice/web/` contains the microphone page and AudioWorklet.
`app/voice/evaluation.py` and `scripts/evaluate_voice.py` provide WER/reporting.

## Lightweight English/Hindi setup

From the project root with the virtual environment activated:

```powershell
pip install -e '.[dev,voice]'
python -m scripts.prepare_voice
```

Preparation explicitly downloads the multilingual `small` faster-whisper model
and Piper `en_US-lessac-medium` and `hi_IN-pratham-medium` voices into ignored
`.local/voice`. Models require several hundred MB of disk space; preparation can
take time. It writes `.local/voice/settings.env` without changing existing secrets.
Merge those voice settings into `.env`, avoiding duplicate keys, and restart the
API. `VOICE_OFFLINE=true` then prevents implicit ASR/model-hub downloads at runtime.
Use `--asr-model tiny`, `base`, `medium` or `large-v3` to choose a different size;
small multilingual CPU/int8 is the initial profile, not a quality guarantee.

Generated configuration has this shape:

```dotenv
VOICE_ENABLED=true
VOICE_ASR_MODEL=C:/ABSOLUTE/PROJECT/.local/voice/asr-small
VOICE_DEVICE=cpu
VOICE_COMPUTE_TYPE=int8
VOICE_OFFLINE=true
VOICE_TTS_BACKEND=piper
VOICE_PIPER_MODELS='{"en":"C:/ABSOLUTE/PROJECT/.local/voice/en_US-lessac-medium.onnx","hi":"C:/ABSOLUTE/PROJECT/.local/voice/hi_IN-pratham-medium.onnx"}'
VOICE_MAX_CONNECTIONS=2
VOICE_ALLOWED_ORIGINS=["http://localhost:8000","http://127.0.0.1:8000"]
```

Piper also requires each model's accompanying `.onnx.json` file. The preparation
command downloads both. Check the source model cards/licenses before redistributing
weights; the maintained Piper engine is GPL-licensed. Downloaded models are ignored
local artifacts, not bundled in application source.

Start normally:

```powershell
uvicorn app.main:app --reload
streamlit run frontend/streamlit_app.py
```

Use **Open voice support** in the customer workspace, or open
`http://localhost:8000/v1/voice`. In local authentication mode, sign in with a
customer account on this separate page. Registration and verification remain in
Streamlit. Admins do not inherit customer permissions. Choose English/Hindi,
connect, permit microphone access, speak and pause. Use headphones to reduce echo.
Say another request during playback or click **Interrupt response** to stop it.
**Disconnect** stops microphone tracks and closes the audio context and socket.

The separate page does not silently copy the Streamlit session token. Credentials
and tokens stay in page memory, never URL query parameters or localStorage. OIDC
mode accepts a customer bearer token; demo mode accepts configured customer headers
through the authenticated start message. Existing order-ownership rules still apply.

## Marathi, Tamil and Telugu output

The ASR and protocol support `en`, `hi`, `mr`, `ta`, `te`. Piper output requires an
appropriate explicitly configured model for each language; it does not create
voices for unsupported languages. The interface lists only configured output
languages and the server rejects missing output voices before loading models.

For broader Indic output an `IndicParler` adapter is implemented using the
AI4Bharat model's two tokenizers and generation API. This is an optional larger
dependency/model profile, not part of the lightweight preparation command:

1. Follow the model publisher's access requirements for
   [AI4Bharat Indic-Parler-TTS](https://huggingface.co/ai4bharat/indic-parler-tts).
   Its model repository may require accepting access conditions through your own
   Hugging Face account; application code does not accept those on your behalf.
2. Install the publisher's `parler-tts` dependency into a compatible environment:
   `pip install git+https://github.com/huggingface/parler-tts.git`.
   Resolve the publisher's Torch/Transformers constraints there; this optional
   stack is not installed or assumed compatible by the default application extras.
3. Set `VOICE_TTS_BACKEND=indic_parler` and
   `VOICE_INDIC_MODEL=ai4bharat/indic-parler-tts`. The adapter uses `VOICE_DEVICE`
   for the model; CPU is supported in code but may be slow. Check model memory
   needs before selecting a GPU profile. For Whisper GPU inference also set a
   compatible `VOICE_COMPUTE_TYPE`, such as float16, and install its CUDA runtime.
4. After access is granted, preload the model and both tokenizers using
   `IndicParler()` in an environment where `VOICE_OFFLINE=false`. Restore
   `VOICE_OFFLINE=true` after the caches are complete. Preloading from the adapter
   uses the same model, prompt tokenizer and description tokenizer as runtime.
5. Restart, select the desired language and measure intelligibility with a native
   speaker. This profile is implemented but not validated by the lightweight
   English/Hindi smoke test. Do not claim measured Marathi/Tamil/Telugu quality
   until testing that actual model profile.

The shared agent receives a trusted language instruction to answer in the selected
language's native script. Identifiers remain unchanged. ASR may mistranscribe order
IDs and code-switching; display transcripts and inspect lookup failures rather
than inventing corrections. Policies are currently English; multilingual policy
search quality is a separate limitation. The agent can retrieve with an English
search query, but no automatic query translator is currently installed.

## Protocol

`GET /v1/voice` serves the page; `WS /v1/voice` is the audio endpoint.
`GET /v1/voice/config` exposes enablement, auth mode and configured language names,
not credentials or model filesystem paths. JavaScript assets are served under
`/v1/voice/client.js` and `/v1/voice/capture.js`.

The socket validates configured browser origins and feature enablement before
accepting. Non-browser clients may omit Origin but must still authenticate.
Send the first message within ten seconds:

```json
{"type":"start","thread_id":"customer-selected-conversation","language":"hi","authorization":"Bearer YOUR_CUSTOMER_TOKEN"}
```

In demo mode use `api_key` and `customer_id` instead of authorization. Extra start
fields, unsupported languages and oversized controls are rejected. Authentication
uses the same customer identity/verified-email functions as chat. It is repeated
before each agent turn so an expired token cannot continue generating new turns.
There is no anonymous audio transcription endpoint.

The server sends `loading`, then `ready` with 16000 Hz and 512 samples per frame.
After ready, send exactly 1024 bytes per binary message: 512 mono, signed,
little-endian PCM16 samples, paced at real time (32 ms per frame). WebM/Opus and
arbitrary WAV files are not accepted as live frame messages. The browser worklet
averages/resamples its microphone input to this format; this is a simple downsampler,
not a studio-quality resampling implementation.

Client controls:

```json
{"type":"interrupt"}
```

```json
{"type":"stop"}
```

Server events:

| Event | Contents / meaning |
| --- | --- |
| `loading` | Authenticated; loading local models |
| `ready` | Input sample rate and frame size; begin live frames |
| `speech_start` | Sustained speech detected |
| `interrupted` | Previous turn ID; clear browser playback |
| `processing` | New turn ID; ASR started |
| `transcript` | Turn ID and recognized text |
| `answer` | Turn ID and the existing agent's final text |
| `audio` | Turn ID, chunk index, WAV format and base64 data |
| `turn_complete` | Turn ID and measured server timings |
| `error` | Safe client-facing failure message; optional turn ID |

Audio is synthesized in chunks of at most 240 text characters after the full agent
answer is available. This improves first-audio time compared with synthesizing a
whole long answer at once, but LLM tokens are not streamed directly to TTS.

## Endpointing, interruptions and limits

- Silero is loaded separately per connection, preserving independent VAD state.
  It evaluates 512-sample frames. Three consecutive frames at probability >= 0.6
  start an utterance; eight frames of pre-roll preserve word onsets. At least eight
  voiced frames are required. Twenty silent frames (~640 ms) end an utterance.
- New sustained speech cancels the pending asynchronous agent task, signals native
  work to stop, and sends `interrupted`. The browser immediately clears playing
  and scheduled audio on this event and ignores stale decoded chunks. The manual
  interruption button also stops playback locally before waiting for the server.
- Whisper checks cancellation between decoded segments; Indic-Parler has a stopping
  criterion. Piper's current sentence and a native ASR kernel can finish after
  cancellation. Their results are discarded. Two worker threads and four admitted
  native jobs bound running/queued heavy work. This is not OS-level process killing.
- Cancellation does not undo a case already committed by a customer tool. Ask for
  current status after interruption; existing active cases are reused normally.
- Utterance buffers cap at 30 seconds; controls at 20,000 characters; output WAV
  chunks at 4 MB; text responses over 12,000 characters remain text-only with an
  explanatory error. Agent transcripts cap at the normal 4,000 characters.
- Connections default to two per API process; sockets last at most 15 minutes,
  wait at most 30 seconds for a frame/control, and turns time out after 180 seconds.
  Model preparation has a 180-second connection timeout. Excessively fast uploads
  and slow browser send buffers are rejected. Limits are process-local, not a
  distributed quota or global tenant rate limiter.
- End-to-end performance depends on hardware, language, model size, model warmup,
  network and Groq latency. Cold loading is shown before ready and excluded from
  turn metrics. Do not overlap text/voice requests on the same conversation ID;
  cross-channel concurrent checkpoint serialization is not added by this feature.

## Measurements and honest reporting

Each completed turn sends these metrics to the UI and logs content-free timing
fields. Use **Download measurements** to save a JSON file with language and timings,
without transcript/answer text or credentials.

| Field | Definition |
| --- | --- |
| `input_audio_ms` | Buffered utterance duration including pre-roll/trailing silence |
| `endpointing_latency_ms` | Last speech-positive frame received to ASR-start time |
| `asr_latency_ms` | Local ASR invocation to complete transcript; includes worker wait |
| `agent_latency_ms` | Existing graph construction/invocation through final answer |
| `tts_latency_ms` | Sum of synthesis chunk invocations, including worker wait |
| `time_to_first_audio_ms` | Last speech-positive frame received to first WAV chunk sent |
| `turn_latency_ms` | Last speech-positive frame received to final audio synthesis/send completion |
| `browser_first_chunk_queue_ms` | First audio-event receipt to scheduled playback, excluding network transit |

The first-audio/turn values include endpointing silence but exclude microphone
capture before the final speech frame, model startup, downstream network transit
and time needed to play the complete answer. These are server-boundary metrics;
they must not be presented as measured mouth-to-ear or completed-playback latency.
Only completed turns appear in browser exports, so report interruption/error counts
separately from logs. The timing summary is not an availability benchmark.

Summarize a browser export with per-language mean/p50/p95:

```powershell
python -m scripts.evaluate_voice --turns PATH_TO_EXPORTED_MEASUREMENTS.json
```

For Hindi versus English ASR, copy
`data/evaluations/voice/manifest.example.json` into a private dataset directory,
for example `.local/voice-benchmark/manifest.json`. Record its six example utterances
as matching filenames, or replace them with a larger balanced test set. Use
consented human speech, mono PCM16 WAV, 16000 Hz, at most 30 seconds each. Keep
references in the native script. Include several speakers, accents/noise levels
and order IDs for a credible portfolio benchmark. Synthetic TTS recordings are
useful smoke tests but cannot establish human-speech ASR performance.

```powershell
python -m scripts.evaluate_voice --manifest .local/voice-benchmark/manifest.json --run-asr
python -m scripts.evaluate_voice --manifest .local/voice-benchmark/manifest.json --run-asr --turns PATH_TO_EXPORTED_MEASUREMENTS.json
```

The CLI does not invoke Groq or open customer cases. It reports corpus WER per
language: total substitutions/insertions/deletions divided by reference word count.
Normalization is NFC, case folding, punctuation-to-space and whitespace tokenization;
it does not transliterate or equate Hindi/English spellings. WER can exceed 1.0.
Missing/invalid recordings are reported as failures, never perfect scores. Reports
include hypotheses/references, ASR times, model/device/compute type and cold load
time separately, under `.local/evaluations/voice-*.json`. Cold first-inference effects
may remain in the first sample; record warm/cold protocol and hardware when comparing.

No human-recording accuracy or live mouth-to-ear performance is claimed by the
automated fixtures. Do not copy fabricated latency/WER numbers onto a resume.

For a reproducible synthetic smoke run after model preparation:

```powershell
python -m scripts.smoke_voice
python -m scripts.smoke_voice --live-agent
```

The first command synthesizes the six example references using Piper and measures
their transcription with the configured prepared Whisper model. The explicit
`--live-agent` variant additionally exercises the real Silero/ASR/Groq/TTS WebSocket
pipeline using paced synthetic audio and in-memory checkpoints. It uses a fresh
fictional customer identity, does not enroll real email, and allows hosted model
calls. It maintains silence frames while waiting, as the microphone client does.
Reports and generated WAVs stay in `.local/voice-smoke`; reports are labeled
`synthetic_piper_smoke_not_human_speech`. This in-process test excludes actual
network transit, microphone hardware and browser playback. Treat any measured
numbers as engineering smoke results, not a human-accent benchmark.

## Verification and privacy boundaries

```powershell
pytest tests/test_voice.py -q
pytest --postgres -q
node tests/voice_browser_checks.cjs
ruff check app tests scripts frontend alembic
ruff format --check app tests scripts frontend alembic
```

Tests use fake speech engines to verify actual WebSocket routing, authentication,
ownership-bound production tools/checkpoints, cancellation, framing, connection
limits and metric calculations without downloading models or using a microphone.
Real-model smoke validation is separate. Browser microphone hardware, echo
suppression, Indic-Parler quality and actual human WER require live checks.

No raw microphone recordings are stored by the live channel. Transcripts and
responses enter the existing conversation/checkpoint system and inference provider;
tools still persist cases/audit data where appropriate. Protect them under the
same retention policy as typed chat. Use HTTPS/WSS and exact allowed origins when
deploying beyond localhost. No billing changes, database migrations, reviewer
permissions or automatic refund execution are added by this channel.

## Primary implementation references

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [Piper Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md)
- [Piper voice catalog and model cards](https://huggingface.co/rhasspy/piper-voices)
- [AI4Bharat Indic-Parler model card](https://huggingface.co/ai4bharat/indic-parler-tts)

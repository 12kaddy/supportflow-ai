"use strict";
const byId = (id) => document.getElementById(id);
const status = (text) => { byId("status").textContent = text; };
let config, socket, context, stream, capture, source;
let ready = false, sources = [], nextAudio = 0, playbackEpoch = 0, activeTurn = 0;
let decodeChain = Promise.resolve(), measurements = [], browserDelays = new Map();
byId("thread").value = crypto.randomUUID();

function message(label, text) {
  const item = document.createElement("div");
  item.className = "message";
  item.textContent = `${label}: ${text}`;
  byId("conversation").appendChild(item);
  item.scrollIntoView({block: "nearest"});
}

function stopPlayback() {
  playbackEpoch += 1;
  for (const audio of sources) { try { audio.stop(); } catch (_) { /* already ended */ } }
  sources = [];
  nextAudio = 0;
}

function disconnect() {
  ready = false;
  stopPlayback();
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  if (capture) { capture.disconnect(); capture = null; }
  if (source) { source.disconnect(); source = null; }
  if (stream) { stream.getTracks().forEach((track) => track.stop()); stream = null; }
  if (context) { context.close(); context = null; }
  byId("credentials").hidden = false;
  byId("connect").disabled = !config?.enabled || !Object.keys(config?.languages || {}).length;
  byId("disconnect").disabled = byId("interrupt").disabled = true;
}

function playAudio(event) {
  const epoch = playbackEpoch, turn = event.turn_id, received = performance.now();
  decodeChain = decodeChain.catch(() => {}).then(async () => {
    if (epoch !== playbackEpoch || turn !== activeTurn || !context) return;
    const bytes = Uint8Array.from(atob(event.data), (character) => character.charCodeAt(0));
    const audio = await context.decodeAudioData(bytes.buffer);
    if (epoch !== playbackEpoch || turn !== activeTurn || !context) return;
    const player = context.createBufferSource();
    player.buffer = audio;
    player.connect(context.destination);
    const scheduled = Math.max(context.currentTime + 0.025, nextAudio);
    if (!browserDelays.has(turn)) {
      browserDelays.set(turn, Math.round(performance.now() - received + (scheduled - context.currentTime) * 1000));
    }
    nextAudio = scheduled + audio.duration;
    sources.push(player);
    player.onended = () => { sources = sources.filter((item) => item !== player); };
    player.start(scheduled);
  }).catch(() => {
    stopPlayback();
    status("Unable to play speech. The text response is still available.");
  });
}

async function connect() {
  byId("connect").disabled = true;
  activeTurn = 0;
  browserDelays.clear();
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error("Use a modern browser on localhost or HTTPS with microphone permission.");
    }
    // Create/resume audio during the user gesture to satisfy autoplay policies.
    context = new AudioContext();
    await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({audio: {
      channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true
    }});
    let authorization = "", apiKey = "", customer = "";
    if (config.auth_mode === "local") {
      const response = await fetch("/v1/auth/login", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({email: byId("email").value, password: byId("password").value})
      });
      const result = await response.json();
      byId("password").value = "";
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Login failed.");
      if (result.user.role !== "customer") throw new Error("Use a customer account for voice support.");
      authorization = `Bearer ${result.access_token}`;
    } else if (config.auth_mode === "oidc") {
      authorization = `Bearer ${byId("token").value}`;
      byId("token").value = "";
    } else {
      apiKey = byId("api-key").value;
      customer = byId("customer").value;
      byId("api-key").value = "";
    }
    await context.audioWorklet.addModule("/v1/voice/capture.js");
    source = context.createMediaStreamSource(stream);
    capture = new AudioWorkletNode(context, "pcm-capture");
    source.connect(capture);
    capture.connect(context.destination); // Worklet emits silence, not microphone loopback.
    socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/v1/voice`);
    const thisSocket = socket;
    const start = {type: "start", language: byId("language").value,
      thread_id: byId("thread").value, authorization, api_key: apiKey, customer_id: customer};
    thisSocket.onopen = () => {
      thisSocket.send(JSON.stringify(start));
      start.authorization = start.api_key = "";
      byId("credentials").hidden = true;
      byId("disconnect").disabled = false;
    };
    thisSocket.onclose = () => { disconnect(); status("Disconnected. Log in again to reconnect."); };
    thisSocket.onerror = () => status("Voice connection failed. Check the API and voice configuration.");
    capture.port.onmessage = ({data}) => {
      if (!ready || thisSocket.readyState !== WebSocket.OPEN) return;
      if (thisSocket.bufferedAmount > 128000) {
        disconnect();
        status("Connection is too slow for live audio. Please reconnect.");
        return;
      }
      thisSocket.send(data);
    };
    thisSocket.onmessage = ({data}) => {
      const event = JSON.parse(data);
      if (event.type === "loading") status("Loading local speech models…");
      if (event.type === "ready") {
        ready = true;
        byId("interrupt").disabled = false;
        status("Listening. Speak, then pause. Speak again to interrupt the response.");
      }
      if (event.type === "interrupted") stopPlayback();
      if (event.type === "speech_start") status("Listening…");
      if (event.type === "processing") { activeTurn = event.turn_id; status("Transcribing and investigating…"); }
      if (event.turn_id && event.turn_id < activeTurn) return;
      if (event.type === "transcript") message("You", event.text);
      if (event.type === "answer") message("SupportFlow", event.text);
      if (event.type === "audio") { status("Speaking. You can interrupt."); playAudio(event); }
      if (event.type === "turn_complete") {
        decodeChain.then(() => {
          const row = {turn_id: event.turn_id, language: start.language, ...event.metrics,
            browser_first_chunk_queue_ms: browserDelays.get(event.turn_id) ?? null};
          measurements.push(row);
          byId("metrics").textContent = JSON.stringify(row, null, 2);
          byId("export").disabled = false;
        });
      }
      if (event.type === "error") status(event.message);
    };
    status("Connecting…");
  } catch (error) {
    disconnect();
    status(error.message || "Unable to start voice support.");
  }
}

byId("connect").onclick = connect;
byId("disconnect").onclick = () => { disconnect(); status("Microphone disconnected."); };
byId("interrupt").onclick = () => {
  stopPlayback();
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: "interrupt"}));
  status("Response interrupted. Speak your next request.");
};
byId("export").onclick = () => {
  const blob = new Blob([JSON.stringify({version: "voice-session-v1", measurements}, null, 2)],
    {type: "application/json"});
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = "supportflow-voice-measurements.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener("beforeunload", disconnect);
fetch("/v1/voice/config").then((response) => response.json()).then((result) => {
  config = result;
  byId(`${config.auth_mode === "local" ? "local" : config.auth_mode === "oidc" ? "token" : "demo"}-fields`).hidden = false;
  for (const [code, name] of Object.entries(config.languages)) {
    const option = document.createElement("option"); option.value = code; option.textContent = name;
    byId("language").appendChild(option);
  }
  const available = config.enabled && Object.keys(config.languages).length;
  byId("connect").disabled = !available;
  status(available ? "Choose your language and connect the microphone." :
    "Voice is disabled or no output voices are configured. Follow docs/voice.md to enable it.");
}).catch(() => status("Cannot load voice configuration."));

/* Browser-independent tests for the real worklet and playback cancellation logic. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const tick = () => new Promise((resolve) => setImmediate(resolve));

for (const rate of [44100, 48000]) {
  let Worklet;
  const frames = [];
  const sandbox = {
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: (frame) => frames.push(frame)}; } },
    sampleRate: rate,
    registerProcessor: (_, implementation) => { Worklet = implementation; },
  };
  vm.runInNewContext(fs.readFileSync("app/voice/web/capture.js", "utf8"), sandbox);
  const worklet = new Worklet();
  for (let offset = 0; offset < rate; offset += 128) {
    worklet.process([[new Float32Array(Math.min(128, rate - offset)).fill(0.5)]]);
  }
  assert.equal(frames.length, 31);
  assert.ok(frames.every((frame) => frame.byteLength === 1024));
  assert.ok(frames.every((frame) => new Int16Array(frame).every((value) => value === 16384)));
}

async function clientChecks() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: "", hidden: false, disabled: false, appendChild() {}, scrollIntoView() {}, click() {},
    });
    return elements.get(id);
  };
  let ws, context, stoppedTracks = 0;
  const players = [];
  class Context {
    constructor() {
      context = this; this.currentTime = 0; this.audioWorklet = {addModule: async () => {}};
    }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
    async decodeAudioData() { return {duration: 1}; }
    createBufferSource() {
      const player = {stopped: false, connect() {}, start() {}, stop() { this.stopped = true; }};
      players.push(player); return player;
    }
  }
  class Socket {
    static OPEN = 1;
    constructor(url) { ws = this; this.url = url; this.sent = []; this.readyState = 1; this.bufferedAmount = 0; }
    send(message) { this.sent.push(message); }
    close() { this.readyState = 3; }
  }
  const sandbox = {
    document: {getElementById: element, createElement: () => element(Math.random().toString())},
    window: {AudioWorkletNode: true, addEventListener() {}},
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop: () => stoppedTracks++}]})}},
    AudioContext: Context,
    AudioWorkletNode: class { constructor() { this.port = {}; } connect() {} disconnect() {} },
    WebSocket: Socket,
    location: {protocol: "http:", host: "localhost:8000"},
    crypto: {randomUUID: () => "thread-1"},
    performance: {now: () => 1},
    atob: (value) => Buffer.from(value, "base64").toString("binary"),
    setTimeout, Blob, URL,
    fetch: async (url) => ({ok: true, json: async () => url.endsWith("config") ?
      {auth_mode: "local", enabled: true, languages: {hi: "Hindi"}} :
      {access_token: "test-only-token", user: {role: "customer"}}}),
  };
  vm.runInNewContext(fs.readFileSync("app/voice/web/client.js", "utf8"), sandbox);
  await tick();
  element("language").value = "hi";
  await element("connect").onclick();
  ws.onopen();
  assert.ok(!ws.url.includes("token"));
  assert.equal(JSON.parse(ws.sent[0]).authorization, "Bearer test-only-token");
  const deliver = (event) => ws.onmessage({data: JSON.stringify(event)});
  deliver({type: "ready"});
  deliver({type: "processing", turn_id: 1});
  deliver({type: "audio", turn_id: 1, data: "AA=="});
  await tick();
  assert.equal(players.length, 1);
  deliver({type: "interrupted", turn_id: 1});
  assert.ok(players[0].stopped, "Barge-in did not stop the playing buffer");
  let resolveDecode;
  context.decodeAudioData = () => new Promise((resolve) => { resolveDecode = resolve; });
  deliver({type: "processing", turn_id: 2});
  deliver({type: "audio", turn_id: 2, data: "AA=="});
  await tick();
  deliver({type: "interrupted", turn_id: 2});
  resolveDecode({duration: 1});
  await tick();
  assert.equal(players.length, 1, "Cancelled decoded audio was scheduled after interruption");
  element("disconnect").onclick();
  assert.equal(stoppedTracks, 1);
  assert.equal(ws.readyState, 3);
  console.log("Voice browser checks passed: resampling, authentication, barge-in, stale decode and microphone cleanup.");
}
clientChecks().catch((error) => { console.error(error); process.exitCode = 1; });

/* Microphone-only AudioWorklet: average downsampling to 16 kHz PCM16, 512 samples/frame. */
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.frame = new Int16Array(512);
    this.offset = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      this.sum += value;
      this.count += 1;
      this.phase += 16000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const sample = Math.max(-1, Math.min(1, this.sum / this.count));
        this.frame[this.offset++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
        this.sum = this.count = 0;
        if (this.offset === 512) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Int16Array(512);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", PCMCapture);

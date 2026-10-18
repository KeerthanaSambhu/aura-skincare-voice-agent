/**
 * AudioWorklet that turns microphone audio into what Gemini Live expects:
 * mono, 16 kHz, 16-bit little-endian PCM, posted in ~40 ms chunks.
 *
 * The browser's AudioContext usually runs at 44.1 or 48 kHz, so this resamples
 * with linear interpolation, carrying the fractional read position across
 * 128-sample render blocks so there are no clicks at block boundaries.
 *
 * Plain JS on purpose: worklet modules are loaded as-is by the browser. The
 * Resampler class is exported so unit tests run this exact code.
 */

export class Resampler {
  /**
   * @param {number} inputRate  source sample rate (e.g. 48000)
   * @param {number} outputRate target sample rate (16000)
   * @param {number} chunkSize  output samples per emitted chunk (640 = 40 ms at 16 kHz)
   */
  constructor(inputRate, outputRate, chunkSize) {
    this.step = inputRate / outputRate;
    this.position = 0; // read position into the next block, in input samples (may be fractional)
    this.previous = 0; // last input sample of the previous block, for interpolation across blocks
    this.chunk = new Int16Array(chunkSize);
    this.filled = 0;
  }

  /** Feed one block of float samples (-1..1). Returns any complete Int16 chunks. */
  push(input) {
    const chunks = [];
    while (this.position < input.length) {
      const index = Math.floor(this.position);
      const frac = this.position - index;
      const a = index === 0 ? this.previous : input[index - 1];
      const b = input[index];
      // position p sits between sample p-1 and p (we shifted by one to use `previous`)
      const sample = a + (b - a) * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      this.chunk[this.filled++] = clamped < 0 ? Math.round(clamped * 0x8000) : Math.round(clamped * 0x7fff);
      if (this.filled === this.chunk.length) {
        chunks.push(this.chunk.slice().buffer);
        this.filled = 0;
      }
      this.position += this.step;
    }
    this.position -= input.length;
    this.previous = input[input.length - 1] ?? this.previous;
    return chunks;
  }
}

if (typeof registerProcessor === "function") {
  class PcmCaptureProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const { targetRate = 16000, chunkMs = 40 } = options.processorOptions ?? {};
      // `sampleRate` is a global in the AudioWorklet scope.
      this.resampler = new Resampler(sampleRate, targetRate, Math.round((targetRate * chunkMs) / 1000));
    }

    process(inputs) {
      const channel = inputs[0]?.[0];
      if (channel && channel.length) {
        for (const buffer of this.resampler.push(channel)) {
          this.port.postMessage(buffer, [buffer]);
        }
      }
      return true; // keep running until the node is disconnected
    }
  }
  registerProcessor("pcm-capture", PcmCaptureProcessor);
}

import { describe, expect, it } from "vitest";
import { Resampler } from "../audio/pcm-capture.worklet.js";
import { arrayBufferToBase64, base64ToArrayBuffer, pcm16ToFloat32, rmsLevel, visualLevel } from "../audio/pcm";

function sine(freq: number, rate: number, seconds: number): Float32Array {
  const out = new Float32Array(Math.round(rate * seconds));
  for (let i = 0; i < out.length; i++) out[i] = 0.5 * Math.sin((2 * Math.PI * freq * i) / rate);
  return out;
}

/** Push a long signal through in 128-sample render blocks, like an AudioWorklet. */
function resample(input: Float32Array, inRate: number, chunk = 640): Int16Array[] {
  const r = new Resampler(inRate, 16000, chunk);
  const chunks: ArrayBuffer[] = [];
  for (let i = 0; i < input.length; i += 128) chunks.push(...r.push(input.subarray(i, i + 128)));
  return chunks.map((b) => new Int16Array(b));
}

describe("microphone resampler (the worklet's own code)", () => {
  it.each([48000, 44100, 16000])("produces 16 kHz output from %i Hz", (rate) => {
    const chunks = resample(sine(440, rate, 1), rate);
    const samples = chunks.length * 640;
    // One second in → about 16,000 samples out (minus the last partial 40 ms chunk).
    expect(samples).toBeGreaterThanOrEqual(15360);
    expect(samples).toBeLessThanOrEqual(16000);
    expect(chunks.every((c) => c.length === 640)).toBe(true); // 40 ms chunks
  });

  it("keeps the pitch: a 440 Hz tone still crosses zero 880 times a second", () => {
    const out = Int16Array.from(resample(sine(440, 48000, 1), 48000).flatMap((c) => Array.from(c)));
    let crossings = 0;
    for (let i = 1; i < out.length; i++) if ((out[i - 1] < 0) !== (out[i] < 0)) crossings++;
    const perSecond = (crossings * 16000) / out.length;
    expect(perSecond).toBeGreaterThan(860);
    expect(perSecond).toBeLessThan(900);
  });

  it("has no jumps at 128-sample block boundaries", () => {
    const out = Int16Array.from(resample(sine(200, 48000, 0.5), 48000).flatMap((c) => Array.from(c)));
    let maxStep = 0;
    for (let i = 1; i < out.length; i++) maxStep = Math.max(maxStep, Math.abs(out[i] - out[i - 1]));
    // A 200 Hz, half-amplitude sine at 16 kHz never moves more than ~1,300 per sample.
    expect(maxStep).toBeLessThan(1400);
  });

  it("clamps out-of-range input to 16-bit limits", () => {
    const r = new Resampler(16000, 16000, 4);
    const [chunk] = r.push(Float32Array.from([2, -2, 2, -2, 2]));
    expect(Array.from(new Int16Array(chunk)).slice(1)).toEqual([32767, -32768, 32767]);
  });
});

describe("PCM helpers", () => {
  it("round-trips base64", () => {
    const bytes = Uint8Array.from({ length: 70000 }, (_, i) => i % 256);
    expect(new Uint8Array(base64ToArrayBuffer(arrayBufferToBase64(bytes.buffer)))).toEqual(bytes);
  });

  it("decodes little-endian 16-bit PCM", () => {
    const buf = new ArrayBuffer(6);
    const view = new DataView(buf);
    view.setInt16(0, 0x4000, true);
    view.setInt16(2, -0x8000, true);
    view.setInt16(4, 0, true);
    expect(Array.from(pcm16ToFloat32(buf))).toEqual([0.5, -1, 0]);
  });

  it("measures levels", () => {
    expect(rmsLevel(new Uint8Array(512).fill(128))).toBe(0);
    expect(rmsLevel(new Uint8Array([0, 255]))).toBeGreaterThan(0.9);
    expect(visualLevel(0.5)).toBe(1);
  });
});

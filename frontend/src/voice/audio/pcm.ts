/** Small, pure helpers for moving 16-bit PCM between the browser and Gemini Live (base64 over JSON). */

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000; // avoid call-stack limits on large buffers
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

/** Little-endian 16-bit PCM bytes → floats in -1..1 (Web Audio's format). */
export function pcm16ToFloat32(buffer: ArrayBuffer): Float32Array<ArrayBuffer> {
  const view = new DataView(buffer);
  const out = new Float32Array(Math.floor(buffer.byteLength / 2));
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 0x8000;
  return out;
}

/** Root-mean-square level of a time-domain analyser frame (0..1, bytes centred on 128). */
export function rmsLevel(frame: Uint8Array): number {
  if (frame.length === 0) return 0;
  let sum = 0;
  for (const v of frame) {
    const x = (v - 128) / 128;
    sum += x * x;
  }
  return Math.sqrt(sum / frame.length);
}

/** Map raw speech RMS (rarely above ~0.3) onto a 0..1 visual level. */
export function visualLevel(rms: number): number {
  return Math.min(1, rms * 3.2);
}

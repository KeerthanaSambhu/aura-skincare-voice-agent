/** Types for the plain-JS AudioWorklet module (it must stay JS: the browser loads it as-is). */
export declare class Resampler {
  constructor(inputRate: number, outputRate: number, chunkSize: number);
  step: number;
  /** Feed one block of float samples (-1..1). Returns any complete 16-bit PCM chunks. */
  push(input: Float32Array): ArrayBuffer[];
}

import { rmsLevel, visualLevel } from "./pcm";
import workletUrl from "./pcm-capture.worklet.js?url";

/**
 * Microphone capture. The AudioContext is created synchronously inside the
 * Start-call click (browsers only allow audio to start from a user gesture);
 * permission is requested afterwards in start().
 */
export class Microphone {
  readonly context: AudioContext;
  private stream: MediaStream | null = null;
  private analyser: AnalyserNode | null = null;
  private node: AudioWorkletNode | null = null;
  private frame = new Uint8Array(512);
  private stopped = false;

  constructor() {
    this.context = new AudioContext();
  }

  /** Ask for the microphone and start emitting 16 kHz PCM chunks. Throws the browser's DOMException on failure. */
  async start(onChunk: (pcm16: ArrayBuffer) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (this.stopped) {
      // The call was cancelled while the permission prompt was open.
      this.releaseStream();
      return;
    }
    await this.context.resume();
    await this.context.audioWorklet.addModule(workletUrl);
    const source = this.context.createMediaStreamSource(this.stream);
    // numberOfOutputs: 0 makes the node a sink, so it's processed without being wired to the speakers.
    this.node = new AudioWorkletNode(this.context, "pcm-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      processorOptions: { targetRate: 16000, chunkMs: 40 },
    });
    this.node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (!this.stopped) onChunk(event.data);
    };
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    source.connect(this.node);
    source.connect(this.analyser);
  }

  /** Current input level, 0..1, for the orb. */
  level(): number {
    if (!this.analyser) return 0;
    this.analyser.getByteTimeDomainData(this.frame);
    return visualLevel(rmsLevel(this.frame));
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }

  /** Stop capture and release the microphone (the browser's mic indicator turns off). */
  stop(): void {
    this.stopped = true;
    if (this.node) this.node.port.onmessage = null;
    this.node?.disconnect();
    this.releaseStream();
    if (this.context.state !== "closed") void this.context.close().catch(() => undefined);
  }
}

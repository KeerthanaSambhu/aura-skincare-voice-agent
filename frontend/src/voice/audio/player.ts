import { base64ToArrayBuffer, pcm16ToFloat32, rmsLevel, visualLevel } from "./pcm";

/**
 * Plays Gemini's 24 kHz 16-bit PCM audio as a gapless queue, and can stop
 * instantly when the customer interrupts (barge-in).
 */
export class AudioPlayer {
  static readonly SAMPLE_RATE = 24000;
  readonly context: AudioContext;
  private readonly analyser: AnalyserNode;
  private readonly sources = new Set<AudioBufferSourceNode>();
  private nextStart = 0;
  private frame = new Uint8Array(512);
  private readonly onPlayingChange: (playing: boolean) => void;

  constructor(onPlayingChange: (playing: boolean) => void) {
    this.onPlayingChange = onPlayingChange;
    // Created inside the click handler so the browser allows audio output.
    this.context = new AudioContext({ sampleRate: AudioPlayer.SAMPLE_RATE });
    this.analyser = this.context.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyser.connect(this.context.destination);
  }

  get playing(): boolean {
    return this.sources.size > 0;
  }

  resume(): Promise<void> {
    return this.context.resume();
  }

  /** Queue one base64 chunk of 24 kHz PCM16 from serverContent.modelTurn. */
  enqueue(base64Pcm: string): void {
    if (this.context.state === "closed") return;
    const samples = pcm16ToFloat32(base64ToArrayBuffer(base64Pcm));
    if (samples.length === 0) return;
    const buffer = this.context.createBuffer(1, samples.length, AudioPlayer.SAMPLE_RATE);
    buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.analyser);
    const startAt = Math.max(this.context.currentTime + 0.02, this.nextStart);
    source.start(startAt);
    this.nextStart = startAt + buffer.duration;
    const wasPlaying = this.playing;
    this.sources.add(source);
    if (!wasPlaying) this.onPlayingChange(true);
    source.onended = () => {
      this.sources.delete(source);
      if (!this.playing) this.onPlayingChange(false);
    };
  }

  /** Stop everything queued right now (Gemini signalled `interrupted`). */
  flush(): void {
    const hadAudio = this.playing;
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already stopped
      }
    }
    this.sources.clear();
    this.nextStart = 0;
    if (hadAudio) this.onPlayingChange(false);
  }

  level(): number {
    if (!this.playing) return 0;
    this.analyser.getByteTimeDomainData(this.frame);
    return visualLevel(rmsLevel(this.frame));
  }

  close(): void {
    this.flush();
    if (this.context.state !== "closed") void this.context.close().catch(() => undefined);
  }
}

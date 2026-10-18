import type { LiveServerMessage } from "@google/genai";
import { ApiError, type EndCallResult, type EndReason, type SessionCreated, type ToolResponse, VoiceApi } from "./api";
import { arrayBufferToBase64 } from "./audio/pcm";
import type { CallState, ConnectingStep, TranscriptEntry } from "./callState";
import { microphoneErrorMessage, sessionErrorMessage } from "./errors";
import type { ConnectLive, FunctionResponse, LiveConnection } from "./live";
import { TranscriptBuilder } from "./transcript";

export type MicrophoneLike = {
  start(onChunk: (pcm16: ArrayBuffer) => void): Promise<void>;
  stop(): void;
  level(): number;
};

export type PlayerLike = {
  readonly playing: boolean;
  resume(): Promise<void>;
  enqueue(base64Pcm: string): void;
  flush(): void;
  close(): void;
  level(): number;
};

export type ControllerDeps = {
  api: Pick<VoiceApi, "createSession" | "callTool" | "endSession">;
  createMicrophone(): MicrophoneLike;
  createPlayer(onPlayingChange: (playing: boolean) => void): PlayerLike;
  connectLive: ConnectLive;
  /** Why this browser can't place calls, or null. */
  unsupportedReason(): string | null;
};

export type CallSnapshot = {
  state: CallState;
  step: ConnectingStep | null;
  transcript: TranscriptEntry[];
  /** Shown to the customer: why the call failed or ended unexpectedly. */
  error: string | null;
  /** Post-call record from the backend, once the call has ended and been saved. */
  record: EndCallResult | null;
  savingRecord: boolean;
  /** Set if the call ended but the backend couldn't save/summarise it. */
  recordError: string | null;
};

const IDLE: CallSnapshot = {
  state: "idle",
  step: null,
  transcript: [],
  error: null,
  record: null,
  savingRecord: false,
  recordError: null,
};

const IN_CALL: CallState[] = ["listening", "thinking", "speaking"];

/**
 * One voice call at a time: microphone → backend session → Gemini Live, plus
 * tool calls, transcript and the post-call record.
 *
 * Rules it enforces:
 * - Nothing is sent to Gemini until it confirms the session (setupComplete).
 * - "Listening/Thinking/Speaking" only show while actually connected.
 * - Every tool call goes to the backend; if that fails, the model is told so
 *   (ok:false, TOOL_UNAVAILABLE) instead of getting nothing.
 * - Every exit path stops the microphone and closes audio.
 */
export class VoiceCallController {
  private snapshot: CallSnapshot = IDLE;
  private readonly listeners = new Set<() => void>();
  private generation = 0; // ignores callbacks from a previous call
  private mic: MicrophoneLike | null = null;
  private player: PlayerLike | null = null;
  private live: LiveConnection | null = null;
  private session: SessionCreated | null = null;
  private transcript = new TranscriptBuilder();
  private pendingTools = 0;
  private awaitingReply = false;
  private clientToolFailures = 0;
  private cancelledToolCalls = new Set<string>();
  private ending = false;
  private readonly deps: ControllerDeps;

  constructor(deps: ControllerDeps) {
    this.deps = deps;
  }

  // ── Subscription (React's useSyncExternalStore) ─────────────────────────
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): CallSnapshot => this.snapshot;

  private set(patch: Partial<CallSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  /** Audio level for the orb: the customer's mic while listening, Aria's audio while speaking. */
  level(): number {
    const state = this.snapshot.state;
    if (state === "speaking") return this.player?.level() ?? 0;
    if (state === "listening") return this.mic?.level() ?? 0;
    return 0;
  }

  get canStart(): boolean {
    return ["idle", "ended", "error"].includes(this.snapshot.state);
  }

  // ── Starting a call ─────────────────────────────────────────────────────
  /** Call from the Start-call click handler: audio contexts must be created during the gesture. */
  async start(): Promise<void> {
    if (!this.canStart) return; // no duplicate sessions
    const unsupported = this.deps.unsupportedReason();
    if (unsupported) {
      this.set({ ...IDLE, state: "error", error: unsupported });
      return;
    }

    const generation = ++this.generation;
    this.resetCallState();
    this.set({ ...IDLE, state: "connecting", step: "microphone" });

    // Created synchronously, inside the click, so the browser lets audio start.
    const mic = this.deps.createMicrophone();
    const player = this.deps.createPlayer(() => this.refreshState());
    this.mic = mic;
    this.player = player;
    void player.resume().catch(() => undefined);

    try {
      await mic.start((chunk) => this.sendMicChunk(chunk, generation));
    } catch (error) {
      return this.fail(generation, microphoneErrorMessage(error));
    }
    if (generation !== this.generation) return;

    this.set({ step: "session" });
    let session: SessionCreated;
    try {
      session = await this.deps.api.createSession();
    } catch (error) {
      return this.fail(generation, sessionErrorMessage(error));
    }
    if (generation !== this.generation) {
      // Cancelled while the session was being created: close it on the server.
      void this.deps.api.endSession(session, [], "customer_ended", 0).catch(() => undefined);
      return;
    }
    this.session = session;

    this.set({ step: "voice" });
    let live: LiveConnection;
    try {
      live = await this.deps.connectLive({
        token: session.token,
        model: session.model,
        apiVersion: session.api_version,
        config: session.live_config,
        callbacks: {
          onMessage: (message) => this.handleMessage(message, generation),
          onClose: () => this.handleUnexpectedClose(generation),
          onError: () => this.handleUnexpectedClose(generation),
        },
      });
    } catch {
      return this.fail(generation, "Couldn't connect to the voice service. Please try again in a moment.");
    }
    if (generation !== this.generation) {
      live.close(); // the customer ended the call while it was connecting
      return;
    }
    this.live = live;
    this.set({ state: "listening", step: null });
    // A cue (not customer speech) so Aria greets first. It isn't added to the transcript.
    live.sendText(session.call_connected_cue);
  }

  private resetCallState(): void {
    this.transcript = new TranscriptBuilder();
    this.session = null;
    this.live = null;
    this.pendingTools = 0;
    this.awaitingReply = false;
    this.clientToolFailures = 0;
    this.cancelledToolCalls = new Set();
    this.ending = false;
  }

  private sendMicChunk(chunk: ArrayBuffer, generation: number): void {
    // Audio before Gemini confirms the session, or after the call, is dropped.
    if (generation !== this.generation || !this.live || !IN_CALL.includes(this.snapshot.state)) return;
    this.live.sendAudio(arrayBufferToBase64(chunk));
  }

  // ── Messages from Gemini ────────────────────────────────────────────────
  handleMessage(message: LiveServerMessage, generation: number): void {
    if (generation !== this.generation || this.ending) return;
    const content = message.serverContent;

    if (content?.interrupted) {
      this.player?.flush(); // barge-in: stop Aria immediately
      this.transcript.endAgentTurn(true);
      this.awaitingReply = false;
    }
    if (content?.inputTranscription?.text) {
      this.transcript.add("customer", content.inputTranscription.text);
      if (content.inputTranscription.finished) this.awaitingReply = true;
    }
    for (const part of content?.modelTurn?.parts ?? []) {
      const data = part.inlineData?.data;
      if (data && (part.inlineData?.mimeType ?? "audio/pcm").startsWith("audio/")) {
        this.player?.enqueue(data);
        this.awaitingReply = false;
      }
    }
    if (content?.outputTranscription?.text) {
      this.transcript.add("agent", content.outputTranscription.text);
      this.awaitingReply = false;
    }
    if (content?.turnComplete) this.transcript.endAgentTurn(false);

    const activity = message.voiceActivity?.voiceActivityType;
    if (activity === "ACTIVITY_END") this.awaitingReply = true;
    if (activity === "ACTIVITY_START") this.awaitingReply = false;

    for (const id of message.toolCallCancellation?.ids ?? []) this.cancelledToolCalls.add(id);
    if (message.toolCall?.functionCalls?.length) void this.handleToolCall(message, generation);

    if (message.goAway) {
      void this.end("timeout", "The call reached its time limit and was ended.");
      return;
    }
    this.refreshState();
  }

  private async handleToolCall(message: LiveServerMessage, generation: number): Promise<void> {
    const calls = message.toolCall?.functionCalls ?? [];
    const session = this.session;
    if (!session) return;
    this.pendingTools += calls.length;
    this.refreshState();

    const responses: FunctionResponse[] = [];
    // In order: a cancellation must see its eligibility check recorded first.
    for (const call of calls) {
      const id = call.id ?? "";
      const name = call.name ?? "";
      let response: ToolResponse;
      try {
        response = await this.deps.api.callTool(session, id, name, call.args ?? {});
      } catch (error) {
        this.clientToolFailures += 1;
        response = {
          ok: false,
          error: {
            code: "TOOL_UNAVAILABLE",
            message:
              error instanceof ApiError && error.code !== "NETWORK_ERROR"
                ? `The order system rejected the request (${error.code}). Don't state any order details.`
                : "Order records couldn't be reached. Don't state any order details; say you can't access them right now.",
          },
        };
      }
      if (!this.cancelledToolCalls.has(id)) responses.push({ id, name, response: response as Record<string, unknown> });
    }

    this.pendingTools = Math.max(0, this.pendingTools - calls.length);
    if (generation !== this.generation || this.ending || !this.live) return;
    if (responses.length) this.live.sendToolResponse(responses);
    this.awaitingReply = true; // Aria will speak the result next
    this.refreshState();
  }

  private refreshState(): void {
    if (!IN_CALL.includes(this.snapshot.state)) return;
    const state: CallState = this.player?.playing
      ? "speaking"
      : this.pendingTools > 0 || this.awaitingReply
        ? "thinking"
        : "listening";
    this.set({ state, transcript: this.transcript.snapshot() });
  }

  // ── Ending ──────────────────────────────────────────────────────────────
  private handleUnexpectedClose(generation: number): void {
    if (generation !== this.generation || this.ending) return;
    void this.end("disconnected", "The call was disconnected.");
  }

  private releaseAudio(): void {
    this.mic?.stop();
    this.player?.close();
    this.live?.close();
    this.mic = null;
    this.player = null;
    this.live = null;
  }

  /** Failure before the call was live. */
  private fail(generation: number, message: string): void {
    if (generation !== this.generation) return;
    this.generation++;
    const session = this.session;
    this.releaseAudio();
    this.set({ ...IDLE, state: "error", error: message });
    // A session was created but never used: close it on the server (best effort, no summary shown).
    if (session) void this.deps.api.endSession(session, [], "error", 0).catch(() => undefined);
  }

  /** End the call (customer pressed End, or the provider ended it), then save and summarise it. */
  async end(reason: EndReason = "customer_ended", message: string | null = null): Promise<void> {
    const { state } = this.snapshot;
    if (this.ending || state === "idle" || state === "ended" || state === "error") return;
    this.ending = true;
    const session = this.session;
    this.generation++; // ignore anything still in flight from this call
    this.releaseAudio();
    this.transcript.finalize();

    if (!session || state === "connecting") {
      // Cancelled before Aria was connected: nothing to summarise.
      if (session) void this.deps.api.endSession(session, [], "customer_ended", 0).catch(() => undefined);
      this.set({ ...IDLE });
      return;
    }

    const transcript = this.transcript.snapshot();
    this.set({ state: "ended", step: null, transcript, error: message, savingRecord: true, recordError: null });
    try {
      const record = await this.deps.api.endSession(session, this.transcript.forBackend(), reason, this.clientToolFailures);
      this.set({ record, savingRecord: false });
    } catch {
      this.set({
        savingRecord: false,
        recordError: "The call ended, but its summary couldn't be saved. The transcript below was not saved.",
      });
    }
  }
}

export function createVoiceCallController(overrides: Partial<ControllerDeps> & Pick<ControllerDeps, "createMicrophone" | "createPlayer" | "connectLive" | "unsupportedReason">): VoiceCallController {
  return new VoiceCallController({ api: overrides.api ?? new VoiceApi(), ...overrides });
}

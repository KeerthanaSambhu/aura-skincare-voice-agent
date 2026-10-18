import type { LiveServerMessage } from "@google/genai";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type EndCallResult, type SessionCreated, type ToolResponse } from "../api";
import { type ControllerDeps, type MicrophoneLike, type PlayerLike, VoiceCallController } from "../controller";
import type { ConnectOptions, FunctionResponse, LiveConnection } from "../live";

// ── Fakes for everything outside the controller ─────────────────────────────

const flush = () => new Promise((r) => setTimeout(r, 0));

class FakeMic implements MicrophoneLike {
  started = false;
  stopped = false;
  onChunk: ((pcm: ArrayBuffer) => void) | null = null;
  failWith: unknown = null;
  async start(onChunk: (pcm: ArrayBuffer) => void) {
    if (this.failWith) throw this.failWith;
    this.onChunk = onChunk;
    this.started = true;
  }
  stop() {
    this.stopped = true;
  }
  level() {
    return 0.3;
  }
  emit() {
    this.onChunk?.(new Uint8Array([1, 0, 2, 0]).buffer);
  }
}

class FakePlayer implements PlayerLike {
  playing = false;
  closed = false;
  flushed = 0;
  queued: string[] = [];
  private readonly onPlayingChange: (p: boolean) => void;
  constructor(onPlayingChange: (p: boolean) => void) {
    this.onPlayingChange = onPlayingChange;
  }
  async resume() {}
  enqueue(b64: string) {
    this.queued.push(b64);
    this.playing = true;
    this.onPlayingChange(true);
  }
  finish() {
    this.playing = false;
    this.onPlayingChange(false);
  }
  flush() {
    this.flushed++;
    this.playing = false;
  }
  close() {
    this.closed = true;
  }
  level() {
    return 0.5;
  }
}

class FakeLive implements LiveConnection {
  audio: string[] = [];
  texts: string[] = [];
  toolResponses: FunctionResponse[][] = [];
  closed = false;
  sendAudio(b64: string) {
    this.audio.push(b64);
  }
  sendText(text: string) {
    this.texts.push(text);
  }
  sendToolResponse(r: FunctionResponse[]) {
    this.toolResponses.push(r);
  }
  close() {
    this.closed = true;
  }
}

function sessionFor(n: number): SessionCreated {
  return {
    session_id: `s${n}`,
    session_secret: `secret${n}`,
    token: `auth_tokens/t${n}`,
    token_expires_at: "",
    new_session_expires_at: "",
    model: "gemini-3.8-live",
    api_version: "v1beta",
    live_config: { tools: [] },
    call_connected_cue: "[call connected]",
  };
}

function setup(overrides: Partial<ControllerDeps> = {}) {
  const mics: FakeMic[] = [];
  const players: FakePlayer[] = [];
  const lives: FakeLive[] = [];
  const connects: ConnectOptions[] = [];
  let sessions = 0;
  const api = {
    createSession: vi.fn(async () => sessionFor(++sessions)),
    callTool: vi.fn(async (_s: SessionCreated, _id: string, name: string, args: unknown): Promise<ToolResponse> => ({
      ok: true,
      result: { name, args },
    })),
    endSession: vi.fn(
      async (s: SessionCreated, transcript: EndCallResult["transcript"]): Promise<EndCallResult> => ({
        session_id: s.session_id,
        transcript,
        summary: { session_id: s.session_id } as EndCallResult["summary"],
      }),
    ),
  };
  const deps: ControllerDeps = {
    api,
    createMicrophone: () => {
      const m = new FakeMic();
      mics.push(m);
      return m;
    },
    createPlayer: (cb) => {
      const p = new FakePlayer(cb);
      players.push(p);
      return p;
    },
    connectLive: vi.fn(async (options: ConnectOptions) => {
      connects.push(options);
      const live = new FakeLive();
      lives.push(live);
      return live;
    }),
    unsupportedReason: () => null,
    ...overrides,
  };
  const controller = new VoiceCallController(deps);
  const states: string[] = [];
  controller.subscribe(() => {
    const s = controller.getSnapshot();
    const label = s.state === "connecting" ? `connecting:${s.step}` : s.state;
    if (states.at(-1) !== label) states.push(label);
  });
  const message = (m: LiveServerMessage) => connects.at(-1)!.callbacks.onMessage(m);
  return { controller, api, deps, mics, players, lives, connects, states, message };
}

const toolCall = (calls: { id: string; name: string; args?: Record<string, unknown> }[]) =>
  ({ toolCall: { functionCalls: calls } }) as LiveServerMessage;

// ── Session initialisation ──────────────────────────────────────────────────

describe("starting a call", () => {
  it("goes microphone → session → voice → listening, then cues the greeting", async () => {
    const t = setup();
    await t.controller.start();
    expect(t.states).toEqual(["connecting:microphone", "connecting:session", "connecting:voice", "listening"]);
    expect(t.connects[0]).toMatchObject({ token: "auth_tokens/t1", model: "gemini-3.8-live", apiVersion: "v1beta" });
    expect(t.lives[0].texts).toEqual(["[call connected]"]);
  });

  it("uses the backend's locked config unchanged", async () => {
    const t = setup();
    await t.controller.start();
    expect(t.connects[0].config).toEqual({ tools: [] });
  });

  it("sends no audio before Gemini confirms the session, and sends it afterwards", async () => {
    let releaseConnect: () => void = () => undefined;
    const t = setup();
    t.deps.connectLive = vi.fn(async (o: ConnectOptions) => {
      t.connects.push(o);
      await new Promise<void>((r) => (releaseConnect = r));
      const live = new FakeLive();
      t.lives.push(live);
      return live;
    });
    const started = t.controller.start();
    await flush();
    t.mics[0].emit(); // mic is live but the call isn't connected yet
    expect(t.controller.getSnapshot().state).toBe("connecting");
    releaseConnect();
    await started;
    expect(t.lives[0].audio).toEqual([]); // the early chunk was dropped, not queued
    t.mics[0].emit();
    expect(t.lives[0].audio).toEqual(["AQACAA=="]);
  });

  it("ignores a second Start while a call is active (no duplicate sessions)", async () => {
    const t = setup();
    const first = t.controller.start();
    const second = t.controller.start();
    await Promise.all([first, second]);
    expect(t.api.createSession).toHaveBeenCalledTimes(1);
    expect(t.mics).toHaveLength(1);
  });

  it("refuses to start in an unsupported browser, without touching the microphone", async () => {
    const t = setup({ unsupportedReason: () => "Voice calls need a secure page (https or localhost)." });
    await t.controller.start();
    expect(t.controller.getSnapshot()).toMatchObject({ state: "error", error: expect.stringMatching(/secure/) });
    expect(t.mics).toHaveLength(0);
  });
});

// ── Failure handling ────────────────────────────────────────────────────────

describe("start failures", () => {
  it("microphone denied: explains, creates no session, releases audio", async () => {
    const t = setup({
      createMicrophone: () => {
        const m = new FakeMic();
        m.failWith = new DOMException("denied", "NotAllowedError");
        t.mics.push(m);
        return m;
      },
    });
    await t.controller.start();
    expect(t.controller.getSnapshot()).toMatchObject({ state: "error", error: expect.stringMatching(/blocked/) });
    expect(t.api.createSession).not.toHaveBeenCalled();
    expect(t.mics[0].stopped).toBe(true);
    expect(t.players[0].closed).toBe(true);
  });

  it("voice not configured on the server: explains and stops the microphone", async () => {
    const t = setup();
    t.api.createSession.mockRejectedValueOnce(new ApiError("VOICE_NOT_CONFIGURED", "", 503));
    await t.controller.start();
    expect(t.controller.getSnapshot()).toMatchObject({ state: "error", error: expect.stringMatching(/isn't set up/) });
    expect(t.mics[0].stopped).toBe(true);
    expect(t.connects).toHaveLength(0);
  });

  it("server unreachable", async () => {
    const t = setup();
    t.api.createSession.mockRejectedValueOnce(new ApiError("NETWORK_ERROR", "", 0));
    await t.controller.start();
    expect(t.controller.getSnapshot().error).toMatch(/Couldn't reach/);
  });

  it("Gemini connection fails: explains, closes the server session, never shows a live state", async () => {
    const t = setup({ connectLive: vi.fn().mockRejectedValue(new Error("1008 policy violation")) });
    await t.controller.start();
    expect(t.states).not.toContain("listening");
    expect(t.controller.getSnapshot()).toMatchObject({ state: "error", error: expect.stringMatching(/voice service/) });
    await flush();
    expect(t.api.endSession).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s1" }), [], "error", 0);
    expect(t.mics[0].stopped).toBe(true);
  });

  it("the call drops mid-way: ends it, saves the record, and says so", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ serverContent: { inputTranscription: { text: "Hello" } } } as LiveServerMessage);
    t.connects[0].callbacks.onClose("server closed");
    await flush();
    const s = t.controller.getSnapshot();
    expect(s).toMatchObject({ state: "ended", error: "The call was disconnected." });
    expect(t.api.endSession).toHaveBeenCalledWith(expect.anything(), [{ speaker: "customer", text: "Hello" }],
      "disconnected", 0);
    expect(s.record).not.toBeNull();
  });

  it("goAway (time limit) ends the call with reason timeout", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ goAway: { timeLeft: "5s" } } as LiveServerMessage);
    await flush();
    expect(t.api.endSession).toHaveBeenCalledWith(expect.anything(), [], "timeout", 0);
    expect(t.controller.getSnapshot().error).toMatch(/time limit/);
  });

  it("cancelling while connecting returns to idle and closes the server session", async () => {
    let releaseSession: (s: SessionCreated) => void = () => undefined;
    const t = setup();
    t.api.createSession.mockImplementationOnce(() => new Promise((r) => (releaseSession = r)));
    const started = t.controller.start();
    await flush();
    await t.controller.end();
    expect(t.controller.getSnapshot().state).toBe("idle");
    expect(t.mics[0].stopped).toBe(true);
    releaseSession(sessionFor(9));
    await started;
    await flush();
    expect(t.connects).toHaveLength(0); // never connected to Gemini
    expect(t.api.endSession).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s9" }), [], "customer_ended", 0);
  });
});

// ── Tools ───────────────────────────────────────────────────────────────────

describe("tool calls", () => {
  let t: ReturnType<typeof setup>;
  beforeEach(async () => {
    t = setup();
    await t.controller.start();
  });

  it("forwards the call to the backend and returns its response to the model", async () => {
    t.message(toolCall([{ id: "fc1", name: "get_order_details", args: { order_id: "ORD-101" } }]));
    expect(t.controller.getSnapshot().state).toBe("thinking");
    await flush();
    expect(t.api.callTool).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s1" }), "fc1",
      "get_order_details", { order_id: "ORD-101" });
    expect(t.lives[0].toolResponses).toEqual([
      [{ id: "fc1", name: "get_order_details", response: { ok: true, result: { name: "get_order_details",
        args: { order_id: "ORD-101" } } } }],
    ]);
  });

  it("passes backend errors (unknown order) through unchanged", async () => {
    t.api.callTool.mockResolvedValueOnce({ ok: false, error: { code: "ORDER_NOT_FOUND", message: "No order" } });
    t.message(toolCall([{ id: "fc1", name: "get_order_details", args: { order_id: "ORD-999" } }]));
    await flush();
    expect(t.lives[0].toolResponses[0][0].response).toEqual({ ok: false, error: { code: "ORDER_NOT_FOUND",
      message: "No order" } });
  });

  it("tells the model when the backend can't be reached, and counts it", async () => {
    t.api.callTool.mockRejectedValueOnce(new ApiError("NETWORK_ERROR", "", 0));
    t.message(toolCall([{ id: "fc1", name: "get_order_details", args: { order_id: "ORD-101" } }]));
    await flush();
    const response = t.lives[0].toolResponses[0][0].response as ToolResponse;
    expect(response.ok).toBe(false);
    expect(response.error?.code).toBe("TOOL_UNAVAILABLE");
    expect(response.error?.message).toMatch(/Don't state any order details/);
    await t.controller.end();
    expect(t.api.endSession).toHaveBeenCalledWith(expect.anything(), [], "customer_ended", 1);
  });

  it("runs several calls in order (eligibility is recorded before a cancellation)", async () => {
    const order: string[] = [];
    t.api.callTool.mockImplementation(async (_s, _id, name) => {
      order.push(name);
      await flush();
      return { ok: true };
    });
    t.message(toolCall([
      { id: "a", name: "check_cancellation_eligibility", args: { order_id: "ORD-103" } },
      { id: "b", name: "cancel_order", args: { order_id: "ORD-103", customer_confirmed: true } },
    ]));
    await new Promise((r) => setTimeout(r, 20));
    expect(order).toEqual(["check_cancellation_eligibility", "cancel_order"]);
    expect(t.lives[0].toolResponses[0].map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("drops responses for calls Gemini cancelled", async () => {
    t.message(toolCall([{ id: "x", name: "get_order_details", args: { order_id: "ORD-101" } }]));
    t.message({ toolCallCancellation: { ids: ["x"] } } as LiveServerMessage);
    await flush();
    expect(t.lives[0].toolResponses).toEqual([]);
  });

  it("never sends tool results after the call ended", async () => {
    let release: (r: ToolResponse) => void = () => undefined;
    t.api.callTool.mockImplementationOnce(() => new Promise((r) => (release = r)));
    t.message(toolCall([{ id: "x", name: "get_order_details", args: { order_id: "ORD-101" } }]));
    await t.controller.end();
    release({ ok: true });
    await flush();
    expect(t.lives[0].toolResponses).toEqual([]);
  });
});

// ── Audio, states, transcript ───────────────────────────────────────────────

describe("during a call", () => {
  it("plays audio, shows speaking only while audio plays, and builds the transcript", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ serverContent: { inputTranscription: { text: "Where is ORD-101?", finished: true } } } as LiveServerMessage);
    expect(t.controller.getSnapshot().state).toBe("thinking"); // customer finished; reply pending
    t.message({ serverContent: { modelTurn: { parts: [{ inlineData: { data: "AAA=", mimeType: "audio/pcm;rate=24000" } }] },
      outputTranscription: { text: "It's out for delivery." } } } as LiveServerMessage);
    expect(t.players[0].queued).toEqual(["AAA="]);
    expect(t.controller.getSnapshot().state).toBe("speaking");
    t.message({ serverContent: { turnComplete: true } } as LiveServerMessage);
    t.players[0].finish();
    expect(t.controller.getSnapshot().state).toBe("listening");
    expect(t.controller.getSnapshot().transcript.map((e) => [e.speaker, e.text])).toEqual([
      ["customer", "Where is ORD-101?"],
      ["agent", "It's out for delivery."],
    ]);
  });

  it("barge-in: an interruption stops Aria's audio at once", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ serverContent: { modelTurn: { parts: [{ inlineData: { data: "AAA=" } }] },
      outputTranscription: { text: "Your order" } } } as LiveServerMessage);
    t.message({ serverContent: { interrupted: true } } as LiveServerMessage);
    expect(t.players[0].flushed).toBe(1);
    expect(t.controller.getSnapshot().state).toBe("listening");
    expect(t.controller.getSnapshot().transcript[0]).toMatchObject({ text: "Your order", interrupted: true });
  });

  it("the greeting cue never appears in the transcript", async () => {
    const t = setup();
    await t.controller.start();
    await t.controller.end();
    expect(t.api.endSession.mock.calls[0][1]).toEqual([]);
  });

  it("reports the mic level while listening and Aria's level while speaking", async () => {
    const t = setup();
    expect(t.controller.level()).toBe(0);
    await t.controller.start();
    expect(t.controller.level()).toBe(0.3);
    t.message({ serverContent: { modelTurn: { parts: [{ inlineData: { data: "AAA=" } }] } } } as LiveServerMessage);
    expect(t.controller.level()).toBe(0.5);
  });
});

// ── Ending, records, session separation ─────────────────────────────────────

describe("ending a call", () => {
  it("releases audio, sends the transcript, and shows the saved record", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ serverContent: { inputTranscription: { text: "Cancel ORD-103" } } } as LiveServerMessage);
    t.message({ serverContent: { outputTranscription: { text: "Sure." } } } as LiveServerMessage);
    const ending = t.controller.end();
    expect(t.controller.getSnapshot()).toMatchObject({ state: "ended", savingRecord: true });
    await ending;
    expect(t.mics[0].stopped && t.players[0].closed && t.lives[0].closed).toBe(true);
    expect(t.api.endSession).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s1" }), [
      { speaker: "customer", text: "Cancel ORD-103" },
      { speaker: "agent", text: "Sure." },
    ], "customer_ended", 0);
    expect(t.controller.getSnapshot()).toMatchObject({ savingRecord: false, recordError: null,
      record: { session_id: "s1" } });
  });

  it("if saving fails, says so and keeps the local transcript visible", async () => {
    const t = setup();
    await t.controller.start();
    t.message({ serverContent: { inputTranscription: { text: "Hello" } } } as LiveServerMessage);
    t.api.endSession.mockRejectedValueOnce(new ApiError("NETWORK_ERROR", "", 0));
    await t.controller.end();
    const s = t.controller.getSnapshot();
    expect(s.record).toBeNull();
    expect(s.recordError).toMatch(/couldn't be saved/);
    expect(s.transcript.map((e) => e.text)).toEqual(["Hello"]);
  });

  it("ending twice only ends once", async () => {
    const t = setup();
    await t.controller.start();
    await Promise.all([t.controller.end(), t.controller.end()]);
    expect(t.api.endSession).toHaveBeenCalledTimes(1);
  });

  it("a new call gets a new session; late messages from the old call are ignored", async () => {
    const t = setup();
    await t.controller.start();
    const oldCallbacks = t.connects[0].callbacks;
    await t.controller.end();
    await t.controller.start();
    expect(t.connects[1].token).toBe("auth_tokens/t2");
    oldCallbacks.onMessage({ serverContent: { inputTranscription: { text: "ghost" } } } as LiveServerMessage);
    oldCallbacks.onMessage(toolCall([{ id: "old", name: "get_order_details", args: { order_id: "ORD-101" } }]));
    await flush();
    expect(t.controller.getSnapshot().transcript).toEqual([]);
    expect(t.api.callTool).not.toHaveBeenCalled();
    t.message(toolCall([{ id: "new", name: "get_order_details", args: { order_id: "ORD-102" } }]));
    await flush();
    expect(t.api.callTool).toHaveBeenCalledWith(expect.objectContaining({ session_id: "s2" }), "new",
      "get_order_details", { order_id: "ORD-102" });
    expect(t.controller.getSnapshot().record).toBeNull(); // previous call's record cleared
  });
});

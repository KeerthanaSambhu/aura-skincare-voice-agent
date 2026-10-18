import { describe, expect, it, vi } from "vitest";
import { ApiError, type SessionCreated, VoiceApi } from "../api";
import { microphoneErrorMessage, sessionErrorMessage, unsupportedReason } from "../errors";
import { TranscriptBuilder } from "../transcript";

const session = { session_id: "abc", session_secret: "s3cret" } as SessionCreated;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("VoiceApi", () => {
  it("creates a session", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(201, { session_id: "abc", token: "auth_tokens/x" }));
    const body = await new VoiceApi("http://api", fetcher).createSession();
    expect(body.token).toBe("auth_tokens/x");
    expect(fetcher).toHaveBeenCalledWith("http://api/api/voice/sessions", expect.objectContaining({ method: "POST" }));
  });

  it("sends the session secret with tool calls, and returns the model-facing response", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(200, { response: { ok: true, result: { status: "Delivered" } } }));
    const response = await new VoiceApi("http://api", fetcher).callTool(session, "c1", "get_order_details", {
      order_id: "ORD-102",
    });
    expect(response).toEqual({ ok: true, result: { status: "Delivered" } });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://api/api/voice/sessions/abc/tool-calls");
    expect(init.headers["X-Session-Secret"]).toBe("s3cret");
    expect(JSON.parse(init.body)).toEqual({ call_id: "c1", name: "get_order_details", args: { order_id: "ORD-102" } });
  });

  it("turns backend errors into ApiError with the backend's code", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      jsonResponse(503, { error: { code: "VOICE_NOT_CONFIGURED", message: "not set up" } }),
    );
    await expect(new VoiceApi("http://api", fetcher).createSession()).rejects.toMatchObject({
      code: "VOICE_NOT_CONFIGURED",
      status: 503,
    });
  });

  it("reports network failures", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(new VoiceApi("http://api", fetcher).createSession()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("times out", async () => {
    const fetcher = vi.fn(
      (_: unknown, init: RequestInit) =>
        new Promise<Response>((_, reject) => init.signal?.addEventListener("abort", () => reject(new Error("aborted")))),
    );
    await expect(new VoiceApi("http://api", fetcher as never, 20).createSession()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("sends the transcript, reason and client tool failures when ending", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(200, { session_id: "abc", transcript: [], summary: {} }));
    await new VoiceApi("http://api", fetcher).endSession(session, [{ speaker: "customer", text: "hi" }], "disconnected", 2);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      transcript: [{ speaker: "customer", text: "hi" }],
      end_reason: "disconnected",
      client_tool_failures: 2,
    });
  });
});

describe("TranscriptBuilder", () => {
  it("joins streamed pieces into turns and keeps speaker order", () => {
    const t = new TranscriptBuilder(() => 0);
    t.add("agent", "Hi, I'm");
    t.add("agent", " Aria.");
    t.add("customer", "Where is");
    t.add("customer", "my order?");
    t.add("agent", "Let me");
    t.add("agent", "check.");
    expect(t.forBackend()).toEqual([
      { speaker: "agent", text: "Hi, I'm Aria." },
      { speaker: "customer", text: "Where is my order?" },
      { speaker: "agent", text: "Let me check." },
    ]);
  });

  it("doesn't add a space before punctuation", () => {
    const t = new TranscriptBuilder();
    t.add("customer", "ORD-101");
    t.add("customer", "?");
    expect(t.forBackend()[0].text).toBe("ORD-101?");
  });

  it("marks an interrupted agent turn and starts a new one after turnComplete", () => {
    const t = new TranscriptBuilder();
    t.add("agent", "Your order is");
    t.endAgentTurn(true);
    t.add("agent", "Sure.");
    const snap = t.snapshot();
    expect(snap.map((e) => [e.text, e.interrupted ?? false])).toEqual([
      ["Your order is", true],
      ["Sure.", false],
    ]);
  });

  it("drops empty turns and respects backend limits", () => {
    const t = new TranscriptBuilder();
    t.add("customer", "   ");
    t.add("agent", "x".repeat(5000));
    const out = t.forBackend();
    expect(out).toHaveLength(1);
    expect(out[0].text).toHaveLength(4000);
  });

  it("ignores missing pieces", () => {
    const t = new TranscriptBuilder();
    t.add("customer", undefined);
    t.add("customer", "");
    expect(t.snapshot()).toEqual([]);
  });
});

describe("error messages", () => {
  it.each([
    ["NotAllowedError", /blocked/],
    ["SecurityError", /blocked/],
    ["NotFoundError", /No microphone/],
    ["NotReadableError", /in use/],
    ["NotSupportedError", /can't capture/],
    ["Weird", /couldn't be started/],
  ])("microphone %s", (name, pattern) => {
    expect(microphoneErrorMessage(new DOMException("x", name))).toMatch(pattern);
  });

  it.each([
    ["VOICE_NOT_CONFIGURED", /isn't set up/],
    ["RATE_LIMITED", /Too many/],
    ["VOICE_PROVIDER_ERROR", /voice service/],
    ["NETWORK_ERROR", /Couldn't reach/],
  ])("session %s", (code, pattern) => {
    expect(sessionErrorMessage(new ApiError(code, "", 0))).toMatch(pattern);
  });

  it("detects unsupported browsers and insecure pages", () => {
    const ok = { isSecureContext: true, mediaDevices: { getUserMedia: () => 0 }, AudioContext: {}, AudioWorkletNode: {} };
    expect(unsupportedReason(ok)).toBeNull();
    expect(unsupportedReason({ ...ok, isSecureContext: false })).toMatch(/secure/);
    expect(unsupportedReason({ ...ok, mediaDevices: undefined })).toMatch(/doesn't support/);
    expect(unsupportedReason({ ...ok, AudioWorkletNode: undefined })).toMatch(/doesn't support/);
  });
});

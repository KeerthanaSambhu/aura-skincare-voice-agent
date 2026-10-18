import { beforeEach, describe, expect, it, vi } from "vitest";

// A stand-in for @google/genai that records how the adapter uses it.
type Callbacks = {
  onmessage: (m: unknown) => void;
  onerror: (e: unknown) => void;
  onclose: (e: { code: number; reason: string }) => void;
};
const sdk = vi.hoisted(() => ({
  hang: false,
  constructorArgs: [] as unknown[],
  connectArgs: [] as { model: string; config: unknown; callbacks: Callbacks }[],
  session: {
    sendRealtimeInput: vi.fn(),
    sendClientContent: vi.fn(),
    sendToolResponse: vi.fn(),
    close: vi.fn(),
  },
}));

vi.mock("@google/genai", () => ({
  GoogleGenAI: class {
    live = {
      connect: async (args: { model: string; config: unknown; callbacks: Callbacks }) => {
        sdk.connectArgs.push(args);
        if (sdk.hang) await new Promise(() => undefined); // socket never opens
        return sdk.session;
      },
    };
    constructor(options: unknown) {
      sdk.constructorArgs.push(options);
    }
  },
}));

import { connectLive } from "../live";

const callbacks = () => ({ onMessage: vi.fn(), onClose: vi.fn(), onError: vi.fn() });
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  sdk.hang = false;
  sdk.constructorArgs.length = 0;
  sdk.connectArgs.length = 0;
  Object.values(sdk.session).forEach((fn) => fn.mockClear());
});

describe("connectLive (Gemini adapter)", () => {
  it("uses the ephemeral token as the key, with the backend's API version, model and config", async () => {
    const pending = connectLive({ token: "auth_tokens/abc", model: "gemini-3.8-live", apiVersion: "v1beta",
      config: { responseModalities: ["AUDIO"] }, callbacks: callbacks() });
    await flush();
    expect(sdk.constructorArgs[0]).toEqual({ apiKey: "auth_tokens/abc", httpOptions: { apiVersion: "v1beta" } });
    expect(sdk.connectArgs[0]).toMatchObject({ model: "gemini-3.8-live", config: { responseModalities: ["AUDIO"] } });
    sdk.connectArgs[0].callbacks.onmessage({ setupComplete: {} });
    await pending;
  });

  it("only resolves after setupComplete, so no audio can be sent before the session is confirmed", async () => {
    let resolved = false;
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks() })
      .then((c) => { resolved = true; return c; });
    await flush();
    expect(resolved).toBe(false); // socket open, but not confirmed
    sdk.connectArgs[0].callbacks.onmessage({ setupComplete: {} });
    await pending;
    expect(resolved).toBe(true);
  });

  it("does not forward messages that arrive before setupComplete", async () => {
    const cb = callbacks();
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: cb });
    await flush();
    sdk.connectArgs[0].callbacks.onmessage({ serverContent: { turnComplete: true } });
    sdk.connectArgs[0].callbacks.onmessage({ setupComplete: {} });
    await pending;
    sdk.connectArgs[0].callbacks.onmessage({ serverContent: { interrupted: true } });
    expect(cb.onMessage.mock.calls).toEqual([[{ setupComplete: {} }], [{ serverContent: { interrupted: true } }]]);
  });

  it("rejects (and closes) if the server closes before confirming, e.g. a rejected token", async () => {
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks() });
    await flush();
    sdk.connectArgs[0].callbacks.onclose({ code: 1008, reason: "invalid token" });
    await expect(pending).rejects.toThrow("invalid token");
    expect(sdk.session.close).toHaveBeenCalled();
  });

  it("times out if setupComplete never arrives", async () => {
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks(),
      timeoutMs: 20 });
    await expect(pending).rejects.toThrow(/Timed out/);
    expect(sdk.session.close).toHaveBeenCalled();
  });

  it("times out even if the socket never opens (a network that silently drops it)", async () => {
    sdk.hang = true;
    const started = Date.now();
    await expect(
      connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks(), timeoutMs: 30 }),
    ).rejects.toThrow(/Timed out/);
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("fails at once if the socket closes before it finishes opening", async () => {
    sdk.hang = true;
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks(),
      timeoutMs: 10_000 });
    await flush();
    sdk.connectArgs[0].callbacks.onclose({ code: 1006, reason: "" });
    await expect(pending).rejects.toThrow(/closed \(1006\)/);
  });

  it("sends audio, text and tool responses in the Live API's formats", async () => {
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: callbacks() });
    await flush();
    sdk.connectArgs[0].callbacks.onmessage({ setupComplete: {} });
    const live = await pending;
    live.sendAudio("AAAA");
    live.sendText("[call connected]");
    live.sendToolResponse([{ id: "1", name: "get_order_details", response: { ok: true } }]);
    live.close();
    expect(sdk.session.sendRealtimeInput).toHaveBeenCalledWith({ audio: { data: "AAAA", mimeType: "audio/pcm;rate=16000" } });
    expect(sdk.session.sendClientContent).toHaveBeenCalledWith({
      turns: [{ role: "user", parts: [{ text: "[call connected]" }] }], turnComplete: true });
    expect(sdk.session.sendToolResponse).toHaveBeenCalledWith({
      functionResponses: [{ id: "1", name: "get_order_details", response: { ok: true } }] });
    expect(sdk.session.close).toHaveBeenCalled();
  });

  it("reports close and errors after the call is live", async () => {
    const cb = callbacks();
    const pending = connectLive({ token: "t", model: "m", apiVersion: "v1beta", config: {}, callbacks: cb });
    await flush();
    sdk.connectArgs[0].callbacks.onmessage({ setupComplete: {} });
    await pending;
    sdk.connectArgs[0].callbacks.onerror(new Error("boom"));
    sdk.connectArgs[0].callbacks.onclose({ code: 1000, reason: "done" });
    expect(cb.onError).toHaveBeenCalled();
    expect(cb.onClose).toHaveBeenCalledWith("done");
  });
});

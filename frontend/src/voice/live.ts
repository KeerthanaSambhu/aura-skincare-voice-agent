/**
 * Thin adapter over @google/genai's Live API, so the call controller depends
 * on a small interface (and tests can supply a fake).
 *
 * The SDK is loaded with a dynamic import when a call starts, which keeps it
 * out of the initial page bundle.
 */
import type { LiveServerMessage } from "@google/genai";

export type FunctionResponse = { id: string; name: string; response: Record<string, unknown> };

export type LiveConnection = {
  sendAudio(base64Pcm16k: string): void;
  sendText(text: string): void;
  sendToolResponse(responses: FunctionResponse[]): void;
  close(): void;
};

export type LiveCallbacks = {
  onMessage(message: LiveServerMessage): void;
  /** The socket closed. `reason` is the server's close reason, if any. */
  onClose(reason: string): void;
  onError(error: unknown): void;
};

export type ConnectOptions = {
  token: string;
  model: string;
  apiVersion: string;
  config: Record<string, unknown>;
  callbacks: LiveCallbacks;
  /** Give up if Gemini hasn't confirmed the session in this time. */
  timeoutMs?: number;
};

export type ConnectLive = (options: ConnectOptions) => Promise<LiveConnection>;

export const connectLive: ConnectLive = async ({ token, model, apiVersion, config, callbacks, timeoutMs = 15_000 }) => {
  const { GoogleGenAI } = await import("@google/genai");
  // The ephemeral token stands in for an API key. It's single-use and locked
  // server-side to this model and config.
  const ai = new GoogleGenAI({ apiKey: token, httpOptions: { apiVersion } });

  let resolveSetup: () => void = () => undefined;
  let rejectSetup: (error: unknown) => void = () => undefined;
  const setupComplete = new Promise<void>((resolve, reject) => {
    resolveSetup = resolve;
    rejectSetup = reject;
  });
  setupComplete.catch(() => undefined); // awaited below; avoid an "unhandled rejection" if it fails early
  let ready = false;
  let timedOut = false;

  // One deadline for the whole attempt: opening the socket AND Gemini's
  // setupComplete. If the network silently drops the socket, connect() itself
  // may never settle, so the timer must start before it, not after.
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      reject(new Error("Timed out waiting for the voice service"));
    }, timeoutMs);
  });

  const connecting = ai.live.connect({
    model,
    config,
    callbacks: {
      onmessage: (message: LiveServerMessage) => {
        if (message.setupComplete && !ready) {
          ready = true;
          resolveSetup();
        }
        if (ready) callbacks.onMessage(message);
      },
      onerror: (event: ErrorEvent) => {
        if (!ready) rejectSetup(event);
        else callbacks.onError(event);
      },
      onclose: (event: CloseEvent) => {
        if (!ready) rejectSetup(new Error(event.reason || `closed (${event.code})`));
        else callbacks.onClose(event.reason ?? "");
      },
    },
  });
  // If we give up first, close the socket whenever it does open.
  void connecting.then((late) => timedOut && late.close()).catch(() => undefined);

  let session: Awaited<typeof connecting>;
  try {
    // An early close/error (e.g. the token is rejected) ends the attempt at once.
    const failedEarly = setupComplete.then(() => new Promise<never>(() => undefined));
    session = await Promise.race([connecting, deadline, failedEarly]);
    try {
      await Promise.race([setupComplete, deadline]);
    } catch (error) {
      session.close();
      throw error;
    }
  } finally {
    clearTimeout(timer);
  }

  return {
    sendAudio: (data) => session.sendRealtimeInput({ audio: { data, mimeType: "audio/pcm;rate=16000" } }),
    sendText: (text) => session.sendClientContent({ turns: [{ role: "user", parts: [{ text }] }], turnComplete: true }),
    sendToolResponse: (functionResponses) => session.sendToolResponse({ functionResponses }),
    close: () => session.close(),
  };
};

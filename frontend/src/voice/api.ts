/**
 * Client for the Aura backend's voice routes (see backend/API_CONTRACT.md).
 * The browser never holds the Gemini API key: it gets a single-use token here.
 */

export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type SessionCreated = {
  session_id: string;
  session_secret: string;
  token: string;
  token_expires_at: string;
  new_session_expires_at: string;
  model: string;
  api_version: string;
  live_config: Record<string, unknown>;
  call_connected_cue: string;
};

export type ToolResponse = { ok: boolean; result?: unknown; error?: { code: string; message: string } };

export type EndCallTurn = { speaker: "customer" | "agent"; text: string };
export type EndReason = "customer_ended" | "disconnected" | "error" | "timeout";

export type CallSummaryJson = Record<string, unknown> & {
  session_id: string;
  customer_intent: string;
  customer_issue: string | null;
  order_id: string | null;
  resolution_status: string;
  final_outcome: string;
  follow_up_required: boolean;
};

export type EndCallResult = { session_id: string; transcript: EndCallTurn[]; summary: CallSummaryJson };

/** A failed backend request, with the backend's error code when it sent one. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

type FetchLike = typeof fetch;

export class VoiceApi {
  private readonly baseUrl: string;
  private readonly fetcher: FetchLike;
  private readonly timeoutMs: number;

  constructor(baseUrl: string = API_BASE_URL, fetcher: FetchLike = (...args) => fetch(...args), timeoutMs = 15_000) {
    this.baseUrl = baseUrl;
    this.fetcher = fetcher;
    this.timeoutMs = timeoutMs;
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, { ...init, signal: controller.signal });
    } catch {
      throw new ApiError("NETWORK_ERROR", "Couldn't reach the Aura server.", 0);
    } finally {
      clearTimeout(timer);
    }
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // fall through: non-JSON body
    }
    if (!response.ok) {
      const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
      throw new ApiError(error?.code ?? "HTTP_ERROR", error?.message ?? `Request failed (${response.status}).`, response.status);
    }
    return body as T;
  }

  createSession(): Promise<SessionCreated> {
    return this.request<SessionCreated>("/api/voice/sessions", { method: "POST" });
  }

  async callTool(session: SessionCreated, callId: string, name: string, args: unknown): Promise<ToolResponse> {
    const body = await this.request<{ response: ToolResponse }>(
      `/api/voice/sessions/${encodeURIComponent(session.session_id)}/tool-calls`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Session-Secret": session.session_secret },
        body: JSON.stringify({ call_id: callId, name, args: args ?? {} }),
      },
    );
    return body.response;
  }

  endSession(
    session: SessionCreated,
    transcript: EndCallTurn[],
    endReason: EndReason,
    clientToolFailures: number,
  ): Promise<EndCallResult> {
    return this.request<EndCallResult>(`/api/voice/sessions/${encodeURIComponent(session.session_id)}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Secret": session.session_secret },
      body: JSON.stringify({ transcript, end_reason: endReason, client_tool_failures: clientToolFailures }),
    });
  }
}

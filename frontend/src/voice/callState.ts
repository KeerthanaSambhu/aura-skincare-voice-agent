/**
 * The call's state machine. Phase 4 drives these transitions from real events:
 *
 *   idle → connecting → listening ⇄ thinking ⇄ speaking → ended
 *                 └────────────── error ──────────────┘
 *
 * - listening: the mic is streaming and no agent audio is playing
 * - thinking:  the customer's turn ended or a tool call is in flight,
 *              before the agent's first audio arrives
 * - speaking:  agent audio is actually playing
 */
export type CallState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "ended" | "error";

/** The three live states the assessment asks the indicator to show. */
export const LIVE_STATES = ["listening", "thinking", "speaking"] as const;
export type LiveState = (typeof LIVE_STATES)[number];

export const STATE_LABEL: Record<CallState, string> = {
  idle: "Not in a call",
  connecting: "Connecting",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  ended: "Call ended",
  error: "Something went wrong",
};

export const STATE_HINT: Record<LiveState, string> = {
  listening: "Aria is hearing you",
  thinking: "Aria is working on an answer",
  speaking: "Aria is replying",
};

/** Every speaker turn in the transcript, kept in arrival order. */
export type TranscriptEntry = {
  id: string;
  speaker: "customer" | "agent";
  text: string;
  at: number;
  /** False while Gemini is still streaming this turn's transcription. */
  final: boolean;
  /** Aria was cut off mid-sentence by the customer. */
  interrupted?: boolean;
};

/** What a "connecting" call is waiting on, shown under the status. */
export type ConnectingStep = "microphone" | "session" | "voice";

export const CONNECTING_DETAIL: Record<ConnectingStep, string> = {
  microphone: "Waiting for microphone permission",
  session: "Starting a secure session",
  voice: "Connecting to Aria",
};

import type { EndCallTurn } from "./api";
import type { TranscriptEntry } from "./callState";

const MAX_TURNS = 400;
const MAX_TURN_CHARS = 4000;

/**
 * Builds a speaker-labelled transcript from Gemini's streaming transcription.
 *
 * Gemini sends text in small pieces (inputTranscription for the customer,
 * outputTranscription for Aria). Consecutive pieces from the same speaker join
 * into one turn; a change of speaker starts a new turn. Nothing is added that
 * Gemini didn't transcribe.
 */
export class TranscriptBuilder {
  private entries: TranscriptEntry[] = [];
  private nextId = 0;
  private readonly now: () => number;

  constructor(now: () => number = () => Date.now()) {
    this.now = now;
  }

  add(speaker: TranscriptEntry["speaker"], piece: string | undefined): void {
    if (!piece) return;
    const last = this.entries[this.entries.length - 1];
    if (last && last.speaker === speaker && !last.final) {
      last.text = join(last.text, piece);
    } else {
      if (last) last.final = true;
      this.entries.push({ id: `t${this.nextId++}`, speaker, text: piece.trimStart(), at: this.now(), final: false });
    }
  }

  /** Aria's turn finished (turnComplete) or was cut off by the customer (interrupted). */
  endAgentTurn(interrupted = false): void {
    const last = this.entries[this.entries.length - 1];
    if (last?.speaker === "agent" && !last.final) {
      last.final = true;
      if (interrupted) last.interrupted = true;
    }
  }

  finalize(): void {
    for (const entry of this.entries) entry.final = true;
  }

  /** A copy for React (new array and objects, so renders see changes). */
  snapshot(): TranscriptEntry[] {
    return this.entries.filter((e) => e.text.trim()).map((e) => ({ ...e, text: e.text.trim() }));
  }

  /** The payload for POST /end: trimmed, non-empty, within the backend's limits. */
  forBackend(): EndCallTurn[] {
    return this.snapshot()
      .slice(-MAX_TURNS)
      .map((e) => ({ speaker: e.speaker, text: e.text.slice(0, MAX_TURN_CHARS) }));
  }
}

/** Join streamed pieces without doubling or losing the space between words. */
function join(existing: string, piece: string): string {
  if (!existing) return piece.trimStart();
  if (/\s$/.test(existing) || /^\s/.test(piece) || /^[,.!?;:'’)]/.test(piece)) return existing + piece;
  return `${existing} ${piece}`;
}

import type { MotionValue } from "motion/react";
import { cn } from "../../lib/cn";
import { type CallState, CONNECTING_DETAIL, type ConnectingStep, type TranscriptEntry } from "../../voice/callState";
import { MagneticButton } from "../ui/MagneticButton";
import { StateIndicator } from "../ui/StateIndicator";
import { VoiceOrb } from "../ui/VoiceOrb";

type VoiceConsoleProps = {
  state: CallState;
  step: ConnectingStep | null;
  transcript: TranscriptEntry[];
  amplitude?: MotionValue<number>;
  error: string | null;
  /** The call has ended and its record is saved or being saved. */
  hasRecord: boolean;
  onStart: () => void;
  onEnd: () => void;
};

const ACTIVE: CallState[] = ["connecting", "listening", "thinking", "speaking"];

export function VoiceConsole({ state, step, transcript, amplitude, error, hasRecord, onStart, onEnd }: VoiceConsoleProps) {
  const active = ACTIVE.includes(state);

  return (
    <section aria-labelledby="console-title" className="mx-auto max-w-6xl px-5 py-16 sm:px-8 md:py-24" id="console">
      <div className="mb-10 max-w-2xl">
        <h2 className="font-display text-4xl leading-tight tracking-[-0.015em] md:text-5xl" id="console-title">
          Call Aria
        </h2>
        <p className="mt-4 text-lg leading-relaxed text-ink-muted">
          Start a call and speak normally. Your browser will ask to use your microphone first.
        </p>
        <p className="mt-3 text-[0.95rem] leading-relaxed text-ink-muted">
          During a call, your voice is sent to Google's Gemini service so Aria can hear and answer you. The microphone
          turns off as soon as the call ends.
        </p>
      </div>

      <div className="grid overflow-hidden rounded-panel border border-line bg-paper-white md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Orb, live state and call controls */}
        <div className="flex flex-col items-center gap-8 border-b border-line px-6 py-10 md:border-b-0 md:border-r md:px-10">
          <VoiceOrb amplitude={amplitude} size="200px" state={state} />
          <StateIndicator detail={state === "connecting" && step ? CONNECTING_DETAIL[step] : null} state={state} />

          <div className="flex w-full flex-wrap justify-center gap-3">
            <MagneticButton disabled={active} onClick={onStart}>
              {state === "ended" || state === "error" ? "Start a new call" : "Start call"}
            </MagneticButton>
            <MagneticButton disabled={!active} onClick={onEnd} variant="quiet">
              {state === "connecting" ? "Cancel" : "End call"}
            </MagneticButton>
          </div>

          {error && (
            <p className="max-w-xs text-center text-sm leading-relaxed text-alert" role="alert">
              {error}
            </p>
          )}
          {state === "ended" && hasRecord && (
            <a className="text-sm font-medium text-olive underline underline-offset-4 hover:text-olive-deep" href="#summary">
              View the call summary
            </a>
          )}
        </div>

        {/* Live transcript: scrolls natively, outside Lenis */}
        <div className="flex min-h-80 flex-col">
          <div className="flex items-baseline justify-between border-b border-line px-6 py-4 md:px-8">
            <h3 className="font-medium">Live transcript</h3>
            <span className="text-sm text-ink-muted">
              {transcript.length === 0 ? "Empty" : `${transcript.length} ${transcript.length === 1 ? "turn" : "turns"}`}
            </span>
          </div>

          <div
            aria-label="Live transcript"
            className="max-h-[28rem] flex-1 overflow-y-auto overscroll-contain px-6 py-6 md:px-8"
            data-lenis-prevent
            role="log"
            tabIndex={0}
          >
            {transcript.length === 0 ? (
              <p className="mx-auto mt-10 max-w-sm text-center leading-relaxed text-ink-muted">
                {active ? "Listening for the first words…" : "What you and Aria say will appear here as you speak."}
              </p>
            ) : (
              <ol className="space-y-5">
                {transcript.map((entry) => (
                  <li className="max-w-prose" key={entry.id}>
                    <p className="text-sm font-medium text-ink-muted">{entry.speaker === "agent" ? "Aria" : "You"}</p>
                    <p className={cn("mt-1 leading-relaxed", !entry.final && "text-ink-muted")}>
                      {entry.text}
                      {entry.interrupted && <span className="text-sm text-ink-muted"> (cut off)</span>}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

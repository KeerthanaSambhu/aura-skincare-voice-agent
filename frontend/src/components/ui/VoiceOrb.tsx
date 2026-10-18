import type { MotionValue } from "motion/react";
import type { CallState } from "../../voice/callState";
import type { AIState } from "./ai-state";
import SiriOrb from "./SiriOrb";

/** Aria's palette: sage, chamomile, blush and vitamin-C amber on an ivory base. */
const ARIA_COLORS = {
  bg: "oklch(96% 0.012 95)",
  c1: "oklch(68% 0.06 140)", // sage
  c2: "oklch(86% 0.06 95)", // chamomile
  c3: "oklch(80% 0.05 30)", // blush
  c4: "oklch(76% 0.09 70)", // vitamin-C amber
};

const ORB_STATE: Record<CallState, AIState> = {
  idle: "idle",
  connecting: "thinking",
  listening: "listening",
  thinking: "thinking",
  speaking: "streaming",
  ended: "idle",
  error: "error",
};

type VoiceOrbProps = {
  state: CallState;
  /**
   * Real audio level, 0–1, from the call's audio graph. Left undefined until
   * the voice pipeline exists, so the orb only breathes and never fakes input.
   */
  amplitude?: MotionValue<number>;
  size?: string;
  className?: string;
};

export function VoiceOrb({ state, amplitude, size = "240px", className }: VoiceOrbProps) {
  return (
    <div aria-hidden="true" className={className}>
      <SiriOrb amplitude={amplitude} animationDuration={24} colors={ARIA_COLORS} size={size} state={ORB_STATE[state]} />
    </div>
  );
}

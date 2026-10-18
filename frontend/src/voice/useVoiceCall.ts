import { useMotionValue, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { AudioPlayer } from "./audio/player";
import { Microphone } from "./audio/microphone";
import { createVoiceCallController, type VoiceCallController } from "./controller";
import { unsupportedReason } from "./errors";
import { connectLive } from "./live";

function browserUnsupportedReason(): string | null {
  return unsupportedReason({
    isSecureContext: window.isSecureContext,
    mediaDevices: navigator.mediaDevices,
    AudioContext: window.AudioContext,
    AudioWorkletNode: window.AudioWorkletNode,
  });
}

let sharedController: VoiceCallController | null = null;

function getController(): VoiceCallController {
  sharedController ??= createVoiceCallController({
    createMicrophone: () => new Microphone(),
    createPlayer: (onPlayingChange) => new AudioPlayer(onPlayingChange),
    connectLive,
    unsupportedReason: browserUnsupportedReason,
  });
  return sharedController;
}

/** React binding for the single voice call on the page. */
export function useVoiceCall() {
  const controller = useMemo(() => getController(), []);
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const amplitude = useMotionValue(0);
  const reduceMotion = useReducedMotion();

  // Feed real audio levels to the orb while a call is live. Zero otherwise,
  // so it never looks like it's hearing something it isn't.
  useEffect(() => {
    if (reduceMotion || !["listening", "speaking"].includes(snapshot.state)) {
      amplitude.set(0);
      return;
    }
    let frame = 0;
    const tick = () => {
      const level = controller.level();
      amplitude.set(amplitude.get() * 0.6 + level * 0.4);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [controller, amplitude, snapshot.state, reduceMotion]);

  // Leaving the page mid-call releases the microphone.
  useEffect(() => {
    const onPageHide = () => void controller.end("disconnected");
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, [controller]);

  const start = useCallback(() => void controller.start(), [controller]);
  const end = useCallback(() => void controller.end("customer_ended"), [controller]);

  return { ...snapshot, amplitude, start, end };
}

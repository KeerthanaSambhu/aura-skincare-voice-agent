import { ApiError } from "./api";

/** Turn microphone, network and provider failures into plain instructions for the customer. */

export function microphoneErrorMessage(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Microphone access was blocked. Allow microphone access for this site in your browser's address bar, then start the call again.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No microphone was found. Connect a microphone and start the call again.";
    case "NotSupportedError":
      return "This browser can't capture microphone audio here. Try a recent version of Chrome, Edge, Firefox or Safari.";
    case "NotReadableError":
    case "AbortError":
      return "Your microphone couldn't start. It may be in use by another app. Close other apps using it and try again.";
    default:
      return "Your microphone couldn't be started. Check your browser's microphone settings and try again.";
  }
}

export function sessionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "VOICE_NOT_CONFIGURED":
        return "Voice calling isn't set up on this server yet, so calls can't start.";
      case "RATE_LIMITED":
        return "Too many calls were started from this device. Please wait a while and try again.";
      case "VOICE_PROVIDER_ERROR":
        return "The voice service couldn't start a call right now. Please try again in a moment.";
      case "NETWORK_ERROR":
        return "Couldn't reach the Aura server. Check your connection and try again.";
      default:
        return "The call couldn't be started. Please try again.";
    }
  }
  return "The call couldn't be started. Please try again.";
}

/** Why the browser can't place a call at all, or null if it can. */
export function unsupportedReason(env: {
  isSecureContext?: boolean;
  mediaDevices?: { getUserMedia?: unknown };
  AudioContext?: unknown;
  AudioWorkletNode?: unknown;
}): string | null {
  if (env.isSecureContext === false) return "Voice calls need a secure page (https or localhost).";
  if (!env.mediaDevices?.getUserMedia || !env.AudioContext || !env.AudioWorkletNode) {
    return "This browser doesn't support voice calls. Try a recent version of Chrome, Edge, Firefox or Safari.";
  }
  return null;
}

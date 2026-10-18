import { ReactLenis } from "lenis/react";
import type { ReactNode } from "react";

/**
 * One global Lenis instance for the page.
 *
 * - autoRaf: Lenis runs its own requestAnimationFrame loop. We don't start a
 *   second one anywhere else, and ReactLenis destroys the instance on unmount.
 * - anchors: in-page links (#console, #orders, …) scroll smoothly. Lenis
 *   honours each section's CSS scroll-margin-top (set in index.css), so
 *   headings land below the sticky nav with or without JavaScript.
 * - respectReducedMotion (Lenis default, stated explicitly): when the visitor
 *   prefers reduced motion, smoothing turns off and anchor jumps are instant.
 * - Nested scroll areas (live transcript, JSON summary) opt out with the
 *   `data-lenis-prevent` attribute so they scroll natively.
 * - Keyboard scrolling (arrows, Page Up/Down, Space) stays native browser
 *   behaviour; Lenis only smooths wheel input by default.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  return (
    <ReactLenis
      root
      options={{
        autoRaf: true,
        anchors: true,
        respectReducedMotion: true,
        lerp: 0.12,
      }}
    >
      {children}
    </ReactLenis>
  );
}

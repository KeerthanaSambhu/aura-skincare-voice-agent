import { type MotionValue, motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { cn } from "../../lib/cn";

/*
 * Original implementation of a word-by-word scroll reveal. The 21st.dev
 * "Scroll word reveal" listing points to a Motion example whose source has no
 * stated license, so this is written from scratch rather than copied.
 *
 * Each word's opacity follows the paragraph's progress through the viewport.
 * Screen readers get the sentence once, as plain text; the animated words are
 * hidden from them. With reduced motion the text simply renders in full.
 */

function Word({ word, progress, range }: { word: string; progress: MotionValue<number>; range: [number, number] }) {
  const opacity = useTransform(progress, range, [0.18, 1]);
  return (
    <motion.span aria-hidden="true" style={{ opacity }}>
      {word}{" "}
    </motion.span>
  );
}

export function ScrollWordReveal({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const shouldReduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.9", "end 0.55"] });
  const words = text.split(" ");

  if (shouldReduceMotion) {
    return <p className={className}>{text}</p>;
  }

  return (
    <p className={cn("relative", className)} ref={ref}>
      <span className="sr-only">{text}</span>
      {words.map((word, i) => {
        const start = i / words.length;
        return <Word key={`${word}-${i}`} progress={scrollYProgress} range={[start, start + 1 / words.length]} word={word} />;
      })}
    </p>
  );
}

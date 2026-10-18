import { motion } from "motion/react";
import { MagneticButton } from "../ui/MagneticButton";
import { VoiceOrb } from "../ui/VoiceOrb";

const ease = [0.22, 1, 0.36, 1] as const;

/*
 * The page's one orchestrated motion moment: headline, then copy, then the orb.
 * MotionConfig in App sets reducedMotion="user", so these become instant fades
 * for visitors who prefer reduced motion.
 */
export function Hero() {
  return (
    <section className="relative overflow-hidden" id="top">
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 pb-12 pt-12 sm:px-8 md:grid-cols-12 md:pb-20 md:pt-24">
        <div className="md:col-span-7">
          <h1 className="font-display text-[clamp(2.75rem,7vw,5.5rem)] font-normal leading-[0.98] tracking-[-0.02em] text-balance">
            {["Talk it through", "with Aria."].map((line, i) => (
              <motion.span
                animate={{ opacity: 1, y: 0 }}
                className="block"
                initial={{ opacity: 0, y: 24 }}
                key={line}
                transition={{ delay: 0.1 + i * 0.12, duration: 0.8, ease }}
              >
                {line}
              </motion.span>
            ))}
          </h1>

          <motion.div
            animate={{ opacity: 1, y: 0 }}
            initial={{ opacity: 0, y: 12 }}
            transition={{ delay: 0.4, duration: 0.7, ease }}
          >
            <p className="mt-8 max-w-[34rem] text-lg leading-relaxed text-ink-muted">
              Aria is Aura's voice support specialist. Ask where your order is, whether it can still be cancelled, or
              how returns work, and she'll answer out loud from Aura's real policies and order records.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-3">
              <MagneticButton href="#console">Call Aria</MagneticButton>
              <MagneticButton href="#orders" variant="quiet">
                See test orders
              </MagneticButton>
            </div>
          </motion.div>
        </div>

        {/* Hidden on phones: the console's orb sits directly below, and two orbs in a row read as repetition. */}
        <motion.figure
          animate={{ opacity: 1, scale: 1 }}
          className="hidden flex-col items-center md:col-span-5 md:flex"
          initial={{ opacity: 0, scale: 0.94 }}
          transition={{ delay: 0.25, duration: 1.1, ease }}
        >
          <div className="grid aspect-square w-full max-w-[22rem] place-items-center rounded-full border border-line bg-paper-white">
            <VoiceOrb size="220px" state="idle" />
          </div>
          <figcaption className="mt-5 font-display text-lg italic text-ink-muted">
            Aria, Aura's voice support specialist
          </figcaption>
        </motion.figure>
      </div>
    </section>
  );
}

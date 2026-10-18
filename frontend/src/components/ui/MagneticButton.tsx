/*
 * Magnetic Button — adapted from SmoothUI by Eduardo Calvo, MIT License
 * (see THIRD_PARTY_NOTICES.md). Copied from the GitHub repo below, not from
 * 21st.dev, which lists a same-name component by the same author.
 * Source: github.com/educlopez/smoothui, packages/smoothui/components/magnetic-button/index.tsx
 * at commit 1534f0d.
 *
 * Changes:
 * - Replaced the shadcn/cva variants with Aura's own two variants, so we don't
 *   pull in class-variance-authority or @radix-ui/react-slot.
 * - Can render as an <a> (for in-page anchors) as well as a <button>.
 * - The original widens its hover zone with a padded wrapper and negative margin.
 *   Next to another button that padding sits on top of its neighbour and steals
 *   clicks, so this version listens for pointer movement on the window instead
 *   and keeps the button's real footprint.
 * - The pull maths is unchanged, and it still only runs on hover-capable
 *   pointers, never when the user prefers reduced motion or it's disabled.
 */

import { motion, useReducedMotion, useSpring } from "motion/react";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "quiet";

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-olive text-paper-white hover:bg-olive-deep disabled:bg-line disabled:text-ink-muted disabled:hover:bg-line",
  quiet:
    "border border-ink/20 text-ink hover:border-ink/50 hover:bg-paper-white disabled:border-line disabled:text-ink-muted/60 disabled:hover:border-line disabled:hover:bg-transparent",
};

const base =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full px-6 text-[0.95rem] font-medium tracking-[0.005em] transition-colors duration-200 disabled:cursor-not-allowed";

type CommonProps = {
  children: ReactNode;
  variant?: Variant;
  /** Fraction of the cursor offset the button follows. */
  strength?: number;
  /** Distance in px at which the pull starts. */
  radius?: number;
  className?: string;
};

type AsButton = CommonProps &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, keyof CommonProps> & { href?: undefined };
type AsAnchor = CommonProps &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, keyof CommonProps> & { href: string };

export type MagneticButtonProps = AsButton | AsAnchor;

export function MagneticButton(props: MagneticButtonProps) {
  const { children, variant = "primary", strength = 0.25, radius = 120, className, ...rest } = props;
  const disabled = "disabled" in rest ? Boolean(rest.disabled) : false;

  const shouldReduceMotion = useReducedMotion();
  const [isHoverDevice, setIsHoverDevice] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  );
  const targetRef = useRef<HTMLElement | null>(null);

  const x = useSpring(0, { bounce: 0.1, duration: 0.4 });
  const y = useSpring(0, { bounce: 0.1, duration: 0.4 });

  useEffect(() => {
    const mediaQuery = window.matchMedia("(hover: hover) and (pointer: fine)");
    const handleChange = (e: MediaQueryListEvent) => setIsHoverDevice(e.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  const isEffectDisabled = disabled || Boolean(shouldReduceMotion) || !isHoverDevice;

  useEffect(() => {
    if (isEffectDisabled) {
      x.set(0);
      y.set(0);
      return;
    }
    const handlePointerMove = (event: PointerEvent) => {
      if (!targetRef.current) return;
      const rect = targetRef.current.getBoundingClientRect();
      const distanceX = event.clientX - (rect.left + rect.width / 2);
      const distanceY = event.clientY - (rect.top + rect.height / 2);
      const distance = Math.hypot(distanceX, distanceY);
      if (distance < radius) {
        const factor = 1 - distance / radius;
        x.set(distanceX * strength * factor);
        y.set(distanceY * strength * factor);
      } else {
        x.set(0);
        y.set(0);
      }
    };
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    return () => window.removeEventListener("pointermove", handlePointerMove);
  }, [isEffectDisabled, radius, strength, x, y]);

  const classes = cn(base, variantClasses[variant], className);

  const inner =
    "href" in rest && rest.href !== undefined ? (
      <a
        {...(rest as AnchorHTMLAttributes<HTMLAnchorElement>)}
        className={classes}
        ref={(el) => {
          targetRef.current = el;
        }}
      >
        {children}
      </a>
    ) : (
      <button
        type="button"
        {...(rest as ButtonHTMLAttributes<HTMLButtonElement>)}
        className={classes}
        ref={(el) => {
          targetRef.current = el;
        }}
      >
        {children}
      </button>
    );

  return (
    <motion.div className="inline-block" style={{ x, y }}>
      {inner}
    </motion.div>
  );
}

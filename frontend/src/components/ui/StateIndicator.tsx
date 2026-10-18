import { type CallState, LIVE_STATES, STATE_HINT, STATE_LABEL } from "../../voice/callState";
import { cn } from "../../lib/cn";

/**
 * Shows which of Listening / Thinking / Speaking is active. Outside a live
 * call none of them is lit, and the line above says so in words, so state is
 * never carried by colour alone. Announced to screen readers politely.
 */
export function StateIndicator({ state, detail }: { state: CallState; detail?: string | null }) {
  const isLive = (LIVE_STATES as readonly string[]).includes(state);

  return (
    <div className="w-full">
      <p aria-live="polite" className="text-center text-sm text-ink-muted" role="status">
        <span className="font-medium text-ink">{STATE_LABEL[state]}</span>
        {isLive && <span>. {STATE_HINT[state as (typeof LIVE_STATES)[number]]}</span>}
        {!isLive && detail && <span>. {detail}…</span>}
      </p>

      <ol aria-hidden="true" className="mt-4 grid grid-cols-3 gap-2">
        {LIVE_STATES.map((s) => {
          const active = s === state;
          return (
            <li
              className={cn(
                "flex items-center justify-center gap-2 rounded-full border px-3 py-2 text-sm transition-colors duration-200",
                active ? "border-olive bg-olive text-paper-white" : "border-line text-ink-muted",
              )}
              key={s}
            >
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  active ? "bg-paper-white" : "bg-line",
                  active && s === "listening" && "animate-pulse",
                )}
              />
              {STATE_LABEL[s]}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

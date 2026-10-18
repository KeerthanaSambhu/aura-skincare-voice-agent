import { useState } from "react";
import type { EndCallResult } from "../../voice/api";
import type { TranscriptEntry } from "../../voice/callState";

type CallSummaryProps = {
  record: EndCallResult | null;
  /** The browser's own transcript, shown only if the record couldn't be saved. */
  localTranscript: TranscriptEntry[];
  saving: boolean;
  recordError: string | null;
};

const INTENT_LABEL: Record<string, string> = {
  ORDER_TRACKING: "Order tracking",
  CANCELLATION: "Cancellation",
  RETURN_REFUND: "Return or refund",
  DAMAGED_OR_DEFECTIVE: "Damaged or defective item",
  SHIPPING_QUESTION: "Shipping question",
  COD_QUESTION: "Cash on delivery question",
  GENERAL_INQUIRY: "General enquiry",
  NO_CONVERSATION: "No conversation",
};

const STATUS_LABEL: Record<string, string> = {
  RESOLVED: "Resolved",
  POLICY_DECLINED: "Declined under policy",
  NEEDS_FOLLOW_UP: "Needs follow-up",
  NOT_DETERMINED: "Outcome not on record",
  NO_CONVERSATION: "No conversation",
};

function Transcript({ turns }: { turns: { speaker: "customer" | "agent"; text: string }[] }) {
  if (turns.length === 0) return <p className="leading-relaxed text-ink-muted">Nothing was said in this call.</p>;
  return (
    <ol className="space-y-4">
      {turns.map((turn, i) => (
        <li key={`${i}-${turn.speaker}`}>
          <p className="text-sm font-medium text-ink-muted">{turn.speaker === "agent" ? "Aria" : "Customer"}</p>
          <p className="mt-1 leading-relaxed">{turn.text}</p>
        </li>
      ))}
    </ol>
  );
}

/** Post-call record: the transcript and the backend's structured summary. Never sample data. */
export function CallSummary({ record, localTranscript, saving, recordError }: CallSummaryProps) {
  const [copied, setCopied] = useState(false);
  const json = record ? JSON.stringify(record.summary, null, 2) : "";
  const summary = record?.summary;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section aria-labelledby="summary-title" className="border-t border-line bg-paper-white" id="summary">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 md:py-24">
        <div className="grid gap-4 md:grid-cols-12">
          <h2
            className="font-display text-4xl leading-tight tracking-[-0.015em] md:col-span-5 md:text-5xl"
            id="summary-title"
          >
            Call summary
          </h2>
          <p className="text-lg leading-relaxed text-ink-muted md:col-span-6 md:col-start-7">
            When a call ends, you'll see the full transcript here, along with a structured summary: what the customer
            wanted, which order it was about, and whether it was resolved.
          </p>
        </div>

        <div aria-live="polite" className="mt-10">
          {saving && (
            <p className="rounded-panel border border-line px-6 py-10 text-center text-ink-muted">Saving the call record…</p>
          )}

          {!saving && recordError && (
            <div className="rounded-panel border border-line px-6 py-8 md:px-10">
              <p className="text-alert" role="alert">
                {recordError}
              </p>
              <div className="mt-6">
                <Transcript turns={localTranscript.map((t) => ({ speaker: t.speaker, text: t.text }))} />
              </div>
            </div>
          )}

          {!saving && record && summary && (
            <div className="grid gap-10 md:grid-cols-12">
              <div className="md:col-span-5">
                <h3 className="font-display text-2xl">Transcript</h3>
                <div className="mt-5 max-h-[32rem] overflow-y-auto overscroll-contain pr-2" data-lenis-prevent tabIndex={0}>
                  <Transcript turns={record.transcript} />
                </div>
              </div>

              <div className="md:col-span-7">
                <h3 className="font-display text-2xl">Outcome</h3>
                <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-y border-line py-5 text-[0.95rem]">
                  <div>
                    <dt className="text-sm text-ink-muted">Customer wanted</dt>
                    <dd>{INTENT_LABEL[summary.customer_intent] ?? summary.customer_intent}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-ink-muted">Order</dt>
                    <dd>{summary.order_id ?? "None looked up"}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-ink-muted">Status</dt>
                    <dd>{STATUS_LABEL[summary.resolution_status] ?? summary.resolution_status}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-ink-muted">Follow-up needed</dt>
                    <dd>{summary.follow_up_required ? "Yes" : "No"}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-sm text-ink-muted">Result</dt>
                    <dd>{summary.final_outcome}</dd>
                  </div>
                </dl>

                <div className="mt-6 flex items-baseline justify-between gap-4">
                  <h4 className="font-medium">Structured summary (JSON)</h4>
                  <button
                    className="rounded-full border border-ink/20 px-4 py-1.5 text-sm hover:border-ink/50"
                    onClick={() => void copy()}
                    type="button"
                  >
                    {copied ? "Copied" : "Copy JSON"}
                  </button>
                </div>
                <pre
                  aria-label="Structured call summary in JSON"
                  className="mt-3 max-h-[28rem] overflow-auto overscroll-contain rounded-slip border border-line bg-paper p-4 text-[0.8rem] leading-relaxed"
                  data-lenis-prevent
                  tabIndex={0}
                >
                  {json}
                </pre>
              </div>
            </div>
          )}

          {!saving && !record && !recordError && (
            <div className="grid place-items-center rounded-panel border border-dashed border-line px-6 py-16 text-center">
              <p className="max-w-sm leading-relaxed text-ink-muted">No calls yet. Start a call with Aria to see its summary.</p>
              <a className="mt-6 font-medium text-olive underline underline-offset-4 hover:text-olive-deep" href="#console">
                Go to the voice console
              </a>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

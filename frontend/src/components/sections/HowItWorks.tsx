import { ScrollWordReveal } from "../ui/ScrollWordReveal";

const STEPS = [
  {
    title: "You speak",
    body: "Your voice streams from the browser to a realtime speech model, which follows what you're saying as you talk.",
  },
  {
    title: "Aria checks",
    body: "When your question needs an order, Aria asks Aura's server to look it up. The server reads the order record and applies the policy rules, so eligibility is decided by code, not guessed.",
  },
  {
    title: "Aria answers",
    body: "She replies out loud using only what the server returned and Aura's published policies. If the answer isn't there, she says so and asks you to clarify.",
  },
];

// Verbatim from section 3 of the assessment brief. Do not reword.
const POLICIES = [
  {
    name: "Shipping",
    rule: "Free delivery on orders above ₹499. Orders below ₹499 have a ₹50 shipping fee. Standard delivery takes 3–5 business days.",
  },
  {
    name: "Return & refund",
    rule: "Returns are accepted within 7 days of delivery for unopened, unused products in original packaging. Damaged or defective products must be reported within 48 hours of delivery with photos for replacement.",
  },
  {
    name: "Cancellation",
    rule: "Orders can be cancelled only while their status is Processing. Once an order is Shipped or Out for Delivery, it cannot be cancelled (customers may refuse delivery at doorstep).",
  },
  {
    name: "Cash on Delivery",
    rule: "COD is available for orders up to ₹2,500. Customers can pay by cash or UPI at the doorstep.",
  },
];

export function HowItWorks() {
  return (
    <section aria-labelledby="how-title" className="mx-auto max-w-6xl px-5 py-16 sm:px-8 md:py-28" id="how">
      <h2 className="sr-only" id="how-title">
        How it works
      </h2>

      <ScrollWordReveal
        className="max-w-4xl font-display text-[clamp(1.9rem,4vw,3.25rem)] leading-[1.15] tracking-[-0.015em]"
        text="Aria answers only from Aura's policies and real order records. When something isn't covered, she tells you instead of guessing."
      />

      <ol className="mt-16 grid gap-10 md:mt-24 md:grid-cols-3 md:gap-12">
        {STEPS.map((step, i) => (
          <li className="border-t border-ink pt-6" key={step.title}>
            <p className="font-display text-lg text-ink-muted">Step {i + 1}</p>
            <h3 className="mt-2 text-xl font-medium">{step.title}</h3>
            <p className="mt-3 leading-relaxed text-ink-muted">{step.body}</p>
          </li>
        ))}
      </ol>

      <div className="mt-20 grid gap-8 md:mt-28 md:grid-cols-12">
        <div className="md:col-span-4">
          <h3 className="font-display text-3xl tracking-[-0.01em]">The policies Aria follows</h3>
          <p className="mt-3 leading-relaxed text-ink-muted">
            Aura Skincare's policies, word for word. Requests outside these, or outside Aura Skincare support, get a polite no.
          </p>
        </div>
        <dl className="divide-y divide-line border-y border-line md:col-span-8">
          {POLICIES.map((policy) => (
            <div className="grid gap-2 py-5 sm:grid-cols-[10rem_1fr] sm:gap-6" key={policy.name}>
              <dt className="font-medium">{policy.name}</dt>
              <dd className="leading-relaxed text-ink-muted">{policy.rule}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}

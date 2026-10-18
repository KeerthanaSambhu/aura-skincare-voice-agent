import { SAMPLE_ORDERS, type SampleOrder } from "../../data/sampleOrders";
import { cn } from "../../lib/cn";

const STATUS_STYLE: Record<SampleOrder["status"], { dot: string; text: string }> = {
  "Out for Delivery": { dot: "bg-amber", text: "text-ink" },
  Delivered: { dot: "bg-sage", text: "text-ink" },
  Processing: { dot: "border border-olive bg-transparent", text: "text-ink" },
};

export function TestOrders() {
  return (
    <section aria-labelledby="orders-title" className="border-y border-line bg-sage-wash/40" id="orders">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 md:py-24">
        <div className="mb-10 grid gap-4 md:grid-cols-12">
          <h2
            className="font-display text-4xl leading-tight tracking-[-0.015em] md:col-span-5 md:text-5xl"
            id="orders-title"
          >
            Test orders
          </h2>
          <p className="text-lg leading-relaxed text-ink-muted md:col-span-6 md:col-start-7">
            The three sample orders from the assessment brief. During a call, say an order number aloud, for example
            “ORD 101”, and Aria will look it up.
          </p>
        </div>

        <ul className="divide-y divide-line overflow-hidden rounded-panel border border-line bg-paper-white">
          {SAMPLE_ORDERS.map((order) => {
            const style = STATUS_STYLE[order.status];
            return (
              <li className="grid gap-6 px-6 py-8 md:grid-cols-12 md:px-10" key={order.id}>
                <div className="md:col-span-3">
                  <p className="font-display text-3xl tracking-[-0.01em]">{order.id}</p>
                  <p className={cn("mt-3 inline-flex items-center gap-2 text-sm font-medium", style.text)}>
                    <span aria-hidden="true" className={cn("size-2 rounded-full", style.dot)} />
                    {order.status}
                  </p>
                </div>

                <dl className="grid grid-cols-2 gap-x-6 gap-y-4 text-[0.95rem] md:col-span-5">
                  <div>
                    <dt className="text-sm text-ink-muted">Customer</dt>
                    <dd>{order.customer}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-ink-muted">Value</dt>
                    <dd>{order.value}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-sm text-ink-muted">Product</dt>
                    <dd>{order.product}</dd>
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <dt className="text-sm text-ink-muted">Carrier</dt>
                    <dd>{order.carrier ? `${order.carrier}, ${order.tracking}` : "None listed"}</dd>
                  </div>
                  <div className="col-span-2 sm:col-span-1">
                    <dt className="text-sm text-ink-muted">Note</dt>
                    <dd>{order.note}</dd>
                  </div>
                </dl>

                <div className="md:col-span-4 md:border-l md:border-line md:pl-8">
                  <p className="text-sm text-ink-muted">Try asking</p>
                  <p className="mt-2 font-display text-xl italic leading-snug">“{order.tryAsking}”</p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

/**
 * Display copy for the Test Orders helper, taken verbatim from the assessment.
 *
 * This is a reference card for evaluators only. Aria never reads this file:
 * from Phase 3 she looks orders up through the backend, which is the single
 * source of truth.
 */
export type SampleOrder = {
  id: string;
  customer: string;
  product: string;
  value: string;
  status: "Out for Delivery" | "Delivered" | "Processing";
  carrier?: string;
  tracking?: string;
  note: string;
  tryAsking: string;
};

export const SAMPLE_ORDERS: SampleOrder[] = [
  {
    id: "ORD-101",
    customer: "Priya Sharma",
    product: "Vitamin C Serum (30ml)",
    value: "₹699",
    status: "Out for Delivery",
    carrier: "BlueDart",
    tracking: "BD-982103",
    note: "Expected by 6 PM today",
    tryAsking: "Where is my order ORD-101? Can I still cancel it?",
  },
  {
    id: "ORD-102",
    customer: "Rahul Verma",
    product: "Hydrating Sunscreen SPF 50",
    value: "₹499",
    status: "Delivered",
    carrier: "Delhivery",
    tracking: "DL-441029",
    note: "Delivered 14 days ago",
    tryAsking: "I opened ORD-102 and want to return it.",
  },
  {
    id: "ORD-103",
    customer: "Ananya Patel",
    product: "Green Tea Face Wash + Toner",
    value: "₹850",
    status: "Processing",
    note: "Ordered 3 hours ago. Eligible for cancellation",
    tryAsking: "Please cancel my order ORD-103.",
  },
];

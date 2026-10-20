import type { BountyEvent, BountyStatus } from "./types";

export type StepState = "done" | "active" | "attention" | "pending" | "void";

export interface RailStep {
  key: "held" | "proven" | "captured" | "paid";
  label: string;
  caption: string;
  state: StepState;
  at: string | null;
}

const lastAt = (events: readonly BountyEvent[], kind: string): string | null => {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.kind === kind) return event.at;
  }
  return null;
};

/**
 * Where the money is, as four steps. The state of a step comes from the
 * events that already happened, so a bounty that went back to `funded` after
 * a failed review shows the hold as done and the proof as pending again.
 */
export function railSteps(status: BountyStatus, events: readonly BountyEvent[]): RailStep[] {
  const funded = lastAt(events, "funded");
  const captured = lastAt(events, "captured");
  const refunded = lastAt(events, "refunded");
  const paid = lastAt(events, "paid");
  const closed = status === "cancelled" || status === "expired";
  const settle = (state: StepState): StepState => (closed && state !== "done" ? "void" : state);
  // A cancelled or expired bounty no longer holds money: an uncaptured hold was voided.
  const holdReleased = closed && !captured;

  return [
    {
      key: "held",
      label: "Authorized",
      caption: holdReleased
        ? funded
          ? "Hold voided, nothing charged"
          : "Never funded"
        : status === "awaiting_payment"
          ? "Waiting for PayPal approval"
          : "PayPal holds the funds",
      state: holdReleased ? "void" : funded ? "done" : status === "awaiting_payment" ? "active" : "pending",
      at: funded,
    },
    {
      key: "proven",
      label: "Proven",
      caption: status === "needs_human" && !captured ? "A human decides" : "CI green, every criterion quoted",
      state: settle(
        captured
          ? "done"
          : status === "in_review"
            ? "active"
            : status === "needs_human"
              ? "attention"
              : "pending",
      ),
      at: captured ? lastAt(events, "verdict") : null,
    },
    {
      key: "captured",
      label: "Captured",
      caption: refunded ? "Refunded to the funder" : "Held funds taken",
      state: refunded ? "void" : settle(captured ? "done" : "pending"),
      at: refunded ?? captured,
    },
    {
      key: "paid",
      label: "Paid out",
      caption: status === "needs_human" && captured ? "Payout failed, a human decides" : "Sent to the solver",
      state: settle(
        paid
          ? "done"
          : status === "released"
            ? "active"
            : status === "needs_human" && captured
              ? "attention"
              : "pending",
      ),
      at: paid,
    },
  ];
}

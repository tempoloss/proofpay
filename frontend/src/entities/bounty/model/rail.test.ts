import { railSteps } from "./rail";
import type { BountyEvent } from "./types";

const event = (kind: string, minute: number): BountyEvent => ({
  kind,
  at: `2026-10-20T10:${String(minute).padStart(2, "0")}:00Z`,
  detail: {},
});

const states = (...args: Parameters<typeof railSteps>) => railSteps(...args).map((step) => step.state);

describe("railSteps", () => {
  it("shows the hold as active while PayPal approval is pending", () => {
    expect(states("awaiting_payment", [event("created", 0)])).toEqual([
      "active",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("marks the proof step for a human when review is unsure before any capture", () => {
    const events = [event("created", 0), event("funded", 1), event("submitted", 2), event("verdict", 3)];
    expect(states("needs_human", events)).toEqual(["done", "attention", "pending", "pending"]);
  });

  it("marks the payout step for a human when the payout fails after capture", () => {
    const events = [event("funded", 1), event("verdict", 3), event("captured", 4), event("payout_failed", 5)];
    expect(states("needs_human", events)).toEqual(["done", "done", "done", "attention"]);
  });

  it("returns to an open hold after a failed review", () => {
    const events = [event("funded", 1), event("submitted", 2), event("verdict", 3), event("rejected", 3)];
    expect(states("funded", events)).toEqual(["done", "pending", "pending", "pending"]);
  });

  it("completes every step once paid, with the capture time on the capture step", () => {
    const events = [event("funded", 1), event("verdict", 3), event("captured", 4), event("paid", 6)];
    const steps = railSteps("paid", events);
    expect(steps.map((step) => step.state)).toEqual(["done", "done", "done", "done"]);
    expect(steps[2]?.at).toBe("2026-10-20T10:04:00Z");
  });

  it("shows a cancelled bounty's hold as released, not as money still held", () => {
    const steps = railSteps("cancelled", [event("funded", 1), event("cancelled", 2)]);
    expect(steps.map((step) => step.state)).toEqual(["void", "void", "void", "void"]);
    expect(steps[0]?.caption).toBe("Hold voided, nothing charged");
  });

  it("marks a captured bounty that was refunded as refunded, not captured", () => {
    const events = [event("funded", 1), event("verdict", 3), event("captured", 4), event("refunded", 7)];
    const steps = railSteps("cancelled", events);
    expect(steps.map((step) => step.state)).toEqual(["done", "done", "void", "void"]);
    expect(steps[2]?.caption).toBe("Refunded to the funder");
  });
});

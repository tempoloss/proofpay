import type { Tone } from "@/shared/ui";
import type { BountyStatus } from "./types";

export const STATUS_META: Record<BountyStatus, { label: string; tone: Tone; pulse: boolean }> = {
  draft: { label: "Draft", tone: "neutral", pulse: false },
  awaiting_payment: { label: "Awaiting payment", tone: "wait", pulse: true },
  funded: { label: "Open", tone: "proof", pulse: false },
  in_review: { label: "In review", tone: "info", pulse: true },
  needs_human: { label: "Needs a human", tone: "wait", pulse: false },
  released: { label: "Paying out", tone: "proof", pulse: true },
  paid: { label: "Paid", tone: "proof", pulse: false },
  cancelled: { label: "Cancelled", tone: "neutral", pulse: false },
  expired: { label: "Expired", tone: "neutral", pulse: false },
};

/** Statuses that the server moves on its own (PayPal, CI, the judge, payouts): keep polling them. */
const MOVING: Partial<Record<BountyStatus, true>> = {
  awaiting_payment: true,
  in_review: true,
  released: true,
};

export const POLL_INTERVAL_MS = 3000;

export const shouldPoll = (status: BountyStatus): boolean => MOVING[status] === true;

export const isBountyStatus = (value: string): value is BountyStatus => Object.hasOwn(STATUS_META, value);

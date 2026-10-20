import {
  BadgeCheck,
  Ban,
  Banknote,
  Bot,
  CircleCheck,
  CircleX,
  Clock,
  FilePlus,
  GitPullRequest,
  Hand,
  Lock,
  type LucideIcon,
  Scale,
  Send,
  TriangleAlert,
  UserRound,
} from "lucide-react";
import type { Tone } from "@/shared/ui";
import type { BountyEvent } from "./types";

export interface EventLine {
  icon: LucideIcon;
  tone: Tone;
  title: string;
  detail: string | null;
  href: string | null;
}

const text = (value: unknown): string | null =>
  typeof value === "string" && value.length > 0 ? value : null;
const count = (value: unknown): number => (typeof value === "number" ? value : 0);

/** One line of the activity feed for a server event. Unknown kinds still render. */
export function describeEvent(event: BountyEvent): EventLine {
  const detail = event.detail;
  switch (event.kind) {
    case "created":
      return { icon: FilePlus, tone: "neutral", title: "Bounty posted", detail: null, href: null };
    case "funded":
      return {
        icon: Lock,
        tone: "proof",
        title: "Funds authorized",
        detail: "PayPal holds the money until the work is proven.",
        href: null,
      };
    case "claimed": {
      const agent = detail.solver_kind === "agent";
      return {
        icon: agent ? Bot : Hand,
        tone: "neutral",
        title: `${text(detail.solver_name) ?? "Someone"} claimed it`,
        detail: agent ? "AI agent via MCP" : "Human solver",
        href: null,
      };
    }
    case "submitted":
      return {
        icon: GitPullRequest,
        tone: "info",
        title: "Pull request submitted",
        detail: text(detail.pr_url),
        href: text(detail.pr_url),
      };
    case "ci": {
      const green = detail.state === "green";
      return {
        icon: green ? CircleCheck : CircleX,
        tone: green ? "proof" : "fail",
        title: green ? "CI passed" : "CI failed",
        detail: text(detail.head_sha)?.slice(0, 7) ?? null,
        href: null,
      };
    }
    case "verdict": {
      const outcome = text(detail.outcome) ?? "unknown";
      return {
        icon: Scale,
        tone: outcome === "pass" ? "proof" : outcome === "fail" ? "fail" : "wait",
        title: `Judge verdict: ${outcome.replace("_", " ")}`,
        detail: `${count(detail.met)} met · ${count(detail.not_met)} not met · ${count(detail.unverified)} unverified`,
        href: null,
      };
    }
    case "captured":
      return { icon: Banknote, tone: "proof", title: "Payment captured", detail: null, href: null };
    case "payout_sent":
      return { icon: Send, tone: "proof", title: "Payout sent", detail: text(detail.batch_id), href: null };
    case "payout_failed":
      return {
        icon: TriangleAlert,
        tone: "fail",
        title: "Payout failed",
        detail: text(detail.reason),
        href: null,
      };
    case "paid":
      return { icon: BadgeCheck, tone: "proof", title: "Paid to the solver", detail: null, href: null };
    case "rejected":
      return {
        icon: CircleX,
        tone: "fail",
        title: "Submission rejected",
        detail: text(detail.reason),
        href: null,
      };
    case "needs_human":
      return {
        icon: UserRound,
        tone: "wait",
        title: "Needs a human decision",
        detail: text(detail.reason),
        href: null,
      };
    case "cancelled":
      return { icon: Ban, tone: "neutral", title: "Cancelled, hold voided", detail: null, href: null };
    case "expired":
      return { icon: Clock, tone: "neutral", title: "Expired, hold voided", detail: null, href: null };
    default:
      return {
        icon: Clock,
        tone: "neutral",
        title: event.kind.replaceAll("_", " "),
        detail: null,
        href: null,
      };
  }
}

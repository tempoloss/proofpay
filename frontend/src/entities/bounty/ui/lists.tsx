import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Bot, ListChecks, UserRound } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { formatExact, formatRelative } from "@/shared/lib/format";
import { Pill } from "@/shared/ui";
import { describeEvent } from "../model/events";
import type { BountyCard, BountyEvent, Claim, Criterion } from "../model/types";
import { Amount, RepoRef, StatusPill } from "./atoms";

/** One bounty on the board. */
export function BountyRow({ bounty }: { bounty: BountyCard }) {
  return (
    <Link
      to="/b/$bountyId"
      params={{ bountyId: bounty.id }}
      className="group grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-6 gap-y-1 rounded-card border border-line bg-surface px-5 py-4 transition-colors hover:border-line-strong hover:bg-raised max-sm:grid-cols-1"
    >
      <div className="row-span-2 flex items-start pt-0.5">
        <Amount value={bounty.amount_usd} />
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <RepoRef owner={bounty.repo_owner} repo={bounty.repo_name} number={bounty.issue_number} />
        <StatusPill status={bounty.status} />
      </div>
      <div className="min-w-0 space-y-1.5">
        <p className="truncate font-medium text-[15px] text-fg">{bounty.title}</p>
        <p className="line-clamp-1 text-muted text-sm">
          <span className="text-faint">Done when </span>
          {bounty.done_when}
        </p>
        <p className="flex items-center gap-3 pt-0.5 font-mono text-[11px] text-faint">
          <span className="inline-flex items-center gap-1">
            <ListChecks className="size-3.5" aria-hidden />
            {bounty.criteria.length} criteria
          </span>
          <span title={formatExact(bounty.created_at)}>{formatRelative(bounty.created_at)}</span>
        </p>
      </div>
    </Link>
  );
}

export function CriteriaList({ criteria }: { criteria: readonly Criterion[] }) {
  return (
    <ol className="space-y-2.5">
      {criteria.map((criterion) => (
        <li key={criterion.id} className="flex gap-3 text-[14px] leading-relaxed">
          <span className="mt-0.5 font-mono text-[11px] text-faint">{criterion.id}</span>
          <span className="text-fg">{criterion.text}</span>
        </li>
      ))}
    </ol>
  );
}

const claimTone = {
  accepted: "proof",
  rejected: "fail",
  needs_human: "wait",
  submitted: "info",
  open: "neutral",
} as const;

export function ClaimList({ claims }: { claims: readonly Claim[] }) {
  if (claims.length === 0) {
    return <p className="text-faint text-sm">No one has claimed this bounty yet.</p>;
  }
  return (
    <ul className="space-y-3">
      {claims.map((claim) => {
        const agent = claim.solver_kind === "agent";
        const tone = claimTone[claim.status as keyof typeof claimTone] ?? "neutral";
        return (
          <li key={claim.id} className="flex items-start gap-3">
            <span
              className={cn(
                "grid size-8 shrink-0 place-items-center rounded-full border",
                agent ? "border-info/30 bg-info/10 text-info" : "border-line-strong bg-raised text-muted",
              )}
            >
              {agent ? <Bot className="size-4" aria-hidden /> : <UserRound className="size-4" aria-hidden />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate font-medium text-fg text-sm">{claim.solver_name}</p>
                <Pill tone={tone} className="capitalize">
                  {claim.status.replaceAll("_", " ")}
                </Pill>
              </div>
              <p className="mt-0.5 flex items-center gap-2 text-faint text-xs">
                <span>{agent ? "AI agent" : "Human"}</span>
                {claim.pr_url ? (
                  <a
                    href={claim.pr_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 font-mono text-muted hover:text-fg"
                  >
                    PR #{claim.pr_url.split("/").at(-1)}
                    <ArrowUpRight className="size-3" aria-hidden />
                  </a>
                ) : null}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const iconTone = {
  proof: "text-proof border-proof/25 bg-proof/10",
  wait: "text-wait border-wait/25 bg-wait/10",
  fail: "text-fail border-fail/25 bg-fail/10",
  info: "text-info border-info/25 bg-info/10",
  neutral: "text-muted border-line-strong bg-raised",
} as const;

/** The bounty's history, newest first. */
export function EventFeed({ events }: { events: readonly BountyEvent[] }) {
  const ordered = [...events].reverse();
  return (
    <ol className="relative space-y-4 before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-line">
      {ordered.map((event, index) => {
        const line = describeEvent(event);
        const Icon = line.icon;
        return (
          <li
            // Events are append-only; position in the reversed list is stable for one render.
            // biome-ignore lint/suspicious/noArrayIndexKey: events have no id in the read model
            key={`${event.kind}-${event.at}-${index}`}
            className="relative flex gap-3"
          >
            <span
              className={cn(
                "z-10 grid size-7 shrink-0 place-items-center rounded-full border",
                iconTone[line.tone],
              )}
            >
              <Icon className="size-3.5" aria-hidden />
            </span>
            <div className="min-w-0 pt-0.5">
              <p className="text-fg text-sm">{line.title}</p>
              {line.detail ? (
                line.href ? (
                  <a
                    href={line.href}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate font-mono text-[11px] text-muted hover:text-fg"
                  >
                    {line.detail}
                  </a>
                ) : (
                  <p className="truncate text-faint text-xs">{line.detail}</p>
                )
              ) : null}
              <p className="mt-0.5 font-mono text-[11px] text-faint" title={formatExact(event.at)}>
                {formatRelative(event.at)}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

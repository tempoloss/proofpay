import { ArrowUpRight } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { formatUsd } from "@/shared/lib/format";
import { Pill } from "@/shared/ui";
import { STATUS_META } from "../model/status";
import type { BountyStatus } from "../model/types";

export function StatusPill({ status, className }: { status: BountyStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <Pill tone={meta.tone} pulse={meta.pulse} className={className}>
      {meta.label}
    </Pill>
  );
}

const amountSize = {
  sm: "text-lg",
  md: "text-2xl",
  lg: "text-[44px] leading-none tracking-tight",
} as const;

export function Amount({
  value,
  size = "md",
  className,
}: {
  value: string;
  size?: keyof typeof amountSize;
  className?: string;
}) {
  return (
    <span className={cn("font-medium font-mono text-proof tabular-nums", amountSize[size], className)}>
      {formatUsd(value)}
    </span>
  );
}

/** `owner/repo#12`, linking to the issue on GitHub. */
export function RepoRef({
  owner,
  repo,
  number,
  href,
  className,
}: {
  owner: string;
  repo: string;
  number: number;
  href?: string;
  className?: string;
}) {
  // One text node group: as separate flex items the parts would get the gap between them.
  const label = (
    <span>
      {owner}/{repo}
      <span className="text-faint">#</span>
      {number}
    </span>
  );
  if (!href) return <span className={cn("font-mono text-[13px] text-muted", className)}>{label}</span>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "group inline-flex items-center font-mono text-[13px] text-muted transition-colors hover:text-fg",
        className,
      )}
    >
      {label}
      <ArrowUpRight
        className="ml-1 size-3.5 opacity-50 transition-opacity group-hover:opacity-100"
        aria-hidden
      />
    </a>
  );
}

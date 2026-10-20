import { Check, CircleDashed, Loader2, TriangleAlert, X } from "lucide-react";
import { cn } from "@/shared/lib/cn";
import { formatExact } from "@/shared/lib/format";
import { type RailStep, railSteps, type StepState } from "../model/rail";
import type { BountyEvent, BountyStatus } from "../model/types";

const node: Record<StepState, string> = {
  done: "border-proof/40 bg-proof/15 text-proof",
  active: "border-info/40 bg-info/10 text-info",
  attention: "border-wait/40 bg-wait/10 text-wait",
  pending: "border-line-strong bg-canvas text-faint",
  void: "border-line bg-canvas text-faint/60",
};

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") return <Check className="size-3.5" strokeWidth={2.5} aria-hidden />;
  if (state === "active") return <Loader2 className="size-3.5 animate-spin" aria-hidden />;
  if (state === "attention") return <TriangleAlert className="size-3.5" aria-hidden />;
  if (state === "void") return <X className="size-3.5" aria-hidden />;
  return <CircleDashed className="size-3.5" aria-hidden />;
}

function Step({ step, last }: { step: RailStep; last: boolean }) {
  return (
    <li className="relative flex min-w-0 flex-1 flex-col gap-3">
      <div className="flex items-center">
        <span
          className={cn(
            "relative z-10 grid size-7 shrink-0 place-items-center rounded-full border transition-colors",
            node[step.state],
          )}
        >
          <StepIcon state={step.state} />
        </span>
        {last ? null : (
          <span
            className={cn("mx-2 h-px flex-1", step.state === "done" ? "bg-proof/40" : "bg-line-strong")}
            aria-hidden
          />
        )}
      </div>
      <div className="min-w-0 pr-3">
        <p className={cn("font-medium text-sm", step.state === "void" ? "text-faint" : "text-fg")}>
          {step.label}
        </p>
        <p className="mt-0.5 text-faint text-xs leading-snug">{step.caption}</p>
        {step.at ? (
          <p className="mt-1 font-mono text-[11px] text-muted tabular-nums">{formatExact(step.at)}</p>
        ) : null}
      </div>
    </li>
  );
}

/** Where the money is right now: authorized → proven → captured → paid out. */
export function MoneyRail({ status, events }: { status: BountyStatus; events: readonly BountyEvent[] }) {
  const steps = railSteps(status, events);
  return (
    <ol className="flex gap-1" aria-label="Payment progress">
      {steps.map((step, index) => (
        <Step key={step.key} step={step} last={index === steps.length - 1} />
      ))}
    </ol>
  );
}

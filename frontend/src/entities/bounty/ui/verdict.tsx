import { CircleCheck, CircleHelp, CircleX, FileCode2, ShieldCheck, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";
import { cn } from "@/shared/lib/cn";
import { Pill } from "@/shared/ui";
import type { Criterion, Verdict, VerdictItem, VerdictState } from "../model/types";

/** The judge's verbatim quote, drawn as the added lines of a diff it must come from. */
export function DiffQuote({ quote, file, state }: { quote: string; file: string; state: VerdictState }) {
  const lines = quote
    .replace(/\r\n/g, "\n")
    .replace(/^\n+|\n+$/g, "")
    .split("\n");
  const verified = state === "met";
  return (
    <figure
      className={cn(
        "overflow-hidden rounded-lg border bg-canvas",
        verified ? "border-proof/20" : state === "unverified" ? "border-wait/25" : "border-line",
      )}
    >
      <figcaption className="flex items-center gap-2 border-line border-b px-3 py-1.5 font-mono text-[11px] text-faint">
        <FileCode2 className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{file || "no file named"}</span>
      </figcaption>
      <pre className="overflow-x-auto py-1.5 font-mono text-[12.5px] leading-6">
        {lines.map((line, index) => (
          <div
            // Lines of one quote never reorder.
            // biome-ignore lint/suspicious/noArrayIndexKey: static list
            key={index}
            className={cn("flex min-w-max", verified ? "bg-proof/[0.07]" : "bg-white/[0.02]")}
          >
            <span
              className={cn(
                "w-8 shrink-0 select-none text-center",
                verified ? "text-proof/70" : "text-faint",
              )}
              aria-hidden
            >
              +
            </span>
            <code className="pr-4 text-fg/90">{line || " "}</code>
          </div>
        ))}
      </pre>
    </figure>
  );
}

const stateIcon = {
  met: <CircleCheck className="size-[18px] text-proof" aria-label="Met" />,
  not_met: <CircleX className="size-[18px] text-fail" aria-label="Not met" />,
  unverified: <CircleHelp className="size-[18px] text-wait" aria-label="Unverified" />,
} as const;

function CheckNote({ item }: { item: VerdictItem }) {
  if (item.state === "met") {
    return (
      <p className="flex items-start gap-1.5 text-proof text-xs leading-relaxed">
        <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          Quote found in the added lines of <span className="font-mono">{item.file}</span>
        </span>
      </p>
    );
  }
  if (item.state === "unverified") {
    return (
      <p className="flex items-start gap-1.5 text-wait text-xs leading-relaxed">
        <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          {item.reason === "criterion missing from judge answer"
            ? "The judge did not answer this criterion. A human decides."
            : "The quote is not in the pull request's added lines. A human decides."}
        </span>
      </p>
    );
  }
  return (
    <p className="flex items-start gap-1.5 text-fail text-xs leading-relaxed">
      <CircleX className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>Not met</span>
    </p>
  );
}

export function VerdictRow({ item, criterion }: { item: VerdictItem; criterion: Criterion | undefined }) {
  return (
    <div className="grid grid-cols-[18px_1fr] gap-x-3 gap-y-2.5">
      <span className="mt-0.5">{stateIcon[item.state]}</span>
      <p className="text-[14px] text-fg leading-relaxed">
        <span className="mr-2 font-mono text-[11px] text-faint">{item.criterion_id}</span>
        {criterion?.text ?? "Unknown criterion"}
      </p>
      <span aria-hidden />
      <div className="min-w-0 space-y-2">
        {item.quote.trim() ? <DiffQuote quote={item.quote} file={item.file} state={item.state} /> : null}
        <CheckNote item={item} />
        {item.reason && item.state !== "unverified" ? (
          <p className="text-muted text-xs leading-relaxed">
            <span className="text-faint">Judge: </span>
            {item.reason}
          </p>
        ) : null}
      </div>
    </div>
  );
}

const outcomeTone = { pass: "proof", fail: "fail", needs_human: "wait" } as const;
const outcomeLabel = { pass: "Pass", fail: "Fail", needs_human: "Needs a human" } as const;
const ciTone = { green: "proof", red: "fail", pending: "info" } as const;

export function VerdictSummary({ verdict }: { verdict: Verdict }) {
  const met = verdict.items.filter((item) => item.state === "met").length;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Pill tone={outcomeTone[verdict.outcome]}>{outcomeLabel[verdict.outcome]}</Pill>
      <Pill tone={ciTone[verdict.ci]}>CI {verdict.ci}</Pill>
      <span className="font-mono text-muted text-xs tabular-nums">
        {met}/{verdict.items.length} proven
      </span>
      {verdict.head_sha ? (
        <span className="font-mono text-faint text-xs" title={`Judged commit ${verdict.head_sha}`}>
          @{verdict.head_sha.slice(0, 7)}
        </span>
      ) : null}
    </div>
  );
}

export function VerdictList({ verdict, criteria }: { verdict: Verdict; criteria: readonly Criterion[] }) {
  return (
    <ul className="divide-y divide-line">
      {verdict.items.map((item, index) => (
        <motion.li
          className="py-4 first:pt-1 last:pb-1"
          key={item.criterion_id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.08, duration: 0.25 }}
        >
          <VerdictRow
            item={item}
            criterion={criteria.find((criterion) => criterion.id === item.criterion_id)}
          />
        </motion.li>
      ))}
    </ul>
  );
}

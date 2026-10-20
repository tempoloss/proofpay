import { TriangleAlert } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";

export type Tone = "proof" | "wait" | "fail" | "info" | "neutral";

const pillTone: Record<Tone, string> = {
  proof: "bg-proof/10 text-proof ring-proof/25",
  wait: "bg-wait/10 text-wait ring-wait/25",
  fail: "bg-fail/10 text-fail ring-fail/25",
  info: "bg-info/10 text-info ring-info/25",
  neutral: "bg-white/[0.04] text-muted ring-white/10",
};

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-card border border-line bg-surface", className)} {...props} />;
}

export function CardHeader({
  title,
  eyebrow,
  actions,
  className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-line border-b px-5 py-4", className)}>
      <div className="min-w-0 space-y-1">
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <h2 className="font-medium text-[15px] text-fg">{title}</h2>
      </div>
      {actions}
    </div>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("font-mono text-[11px] text-proof uppercase tracking-[0.16em]", className)}>
      {children}
    </p>
  );
}

export function Pill({
  tone = "neutral",
  pulse = false,
  children,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 font-medium text-xs ring-1 ring-inset",
        pillTone[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full bg-current", pulse && "animate-pulse-soft")} aria-hidden />
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-white/[0.045]", className)} />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-card border border-line border-dashed px-6 py-14 text-center",
        className,
      )}
    >
      {icon ? <div className="text-faint [&_svg]:size-6">{icon}</div> : null}
      <p className="font-medium text-fg">{title}</p>
      {description ? <p className="max-w-sm text-muted text-sm">{description}</p> : null}
      {action}
    </div>
  );
}

/** An inline error or warning; `title` is the headline, children the detail. */
export function Alert({
  tone = "fail",
  title,
  children,
  className,
}: {
  tone?: "fail" | "wait";
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-lg border px-4 py-3 text-sm",
        tone === "fail"
          ? "border-fail/25 bg-fail/[0.06] text-fail"
          : "border-wait/25 bg-wait/[0.06] text-wait",
        className,
      )}
    >
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{title}</p>
        {children ? <div className="text-muted">{children}</div> : null}
      </div>
    </div>
  );
}

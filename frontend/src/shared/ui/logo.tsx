import { cn } from "../lib/cn";

/** ProofPay mark: a ledger cell with a proof tick. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={cn("size-6", className)}>
      <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" stroke="currentColor" strokeOpacity="0.3" />
      <path
        d="M7.6 12.3l2.9 2.9 5.9-6.8"
        stroke="var(--color-proof)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center gap-2 font-semibold text-[15px] tracking-tight", className)}
    >
      <LogoMark />
      <span>
        Proof<span className="text-muted">Pay</span>
      </span>
    </span>
  );
}

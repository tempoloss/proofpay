import { Link } from "@tanstack/react-router";
import { ArrowRight, BadgeCheck } from "lucide-react";
import { VerdictList, VerdictSummary } from "@/entities/bounty";
import { buttonVariants, Card, Eyebrow } from "@/shared/ui";

const SAMPLE_CRITERIA = [
  { id: "c1", text: "divide(a, 0) returns None instead of raising ZeroDivisionError" },
  { id: "c2", text: "A test in tests/ covers division by zero" },
];

const SAMPLE_VERDICT = {
  outcome: "pass",
  ci: "green",
  items: [
    {
      criterion_id: "c1",
      state: "met",
      quote: "    if b == 0:\n        return None",
      file: "src/tinycalc/__init__.py",
      reason: "The guard returns None before dividing.",
    },
    {
      criterion_id: "c2",
      state: "met",
      quote: "def test_divide_by_zero_returns_none():\n    assert divide(1, 0) is None",
      file: "tests/test_tinycalc.py",
      reason: "A dedicated test asserts the new behaviour.",
    },
  ],
} as const;

function ProofSample() {
  return (
    <Card className="relative overflow-hidden shadow-[0_40px_120px_-40px_rgba(52,211,153,0.28)]">
      <div className="flex items-center justify-between gap-3 border-line border-b px-5 py-3.5">
        <div className="space-y-0.5">
          <p className="font-mono text-[11px] text-faint">example · tinycalc#1 · $25.00</p>
          <p className="font-medium text-fg text-sm">Verdict</p>
        </div>
        <VerdictSummary verdict={{ ...SAMPLE_VERDICT, items: [...SAMPLE_VERDICT.items] }} />
      </div>
      <div className="px-5 py-3">
        <VerdictList
          verdict={{ ...SAMPLE_VERDICT, items: [...SAMPLE_VERDICT.items] }}
          criteria={SAMPLE_CRITERIA}
        />
      </div>
      <div className="flex items-center gap-2 border-line border-t bg-proof/[0.05] px-5 py-3 text-proof text-sm">
        <BadgeCheck className="size-4" aria-hidden />
        Captured and paid out to the solver
      </div>
    </Card>
  );
}

export function Hero() {
  return (
    <section className="grid items-center gap-12 pt-4 lg:grid-cols-[1.05fr_1fr]">
      <div className="space-y-7">
        <Eyebrow>Escrow for GitHub issues</Eyebrow>
        <h1 className="font-serif text-[68px] text-fg leading-[0.92] tracking-[-0.01em] max-sm:text-5xl">
          Pay for proof,
          <br />
          <span className="text-muted italic">not promises.</span>
        </h1>
        <p className="max-w-xl text-[17px] text-muted leading-relaxed">
          Put money on an issue and PayPal holds it. It is released only when CI is green and an AI judge
          proves every acceptance criterion with a quote from the pull request. Code checks every quote;
          anything unproven goes to a human.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link to="/new" className={buttonVariants({ variant: "primary", size: "lg" })}>
            Post a bounty
            <ArrowRight aria-hidden />
          </Link>
          <a href="#how" className={buttonVariants({ variant: "ghost", size: "lg" })}>
            How it works
          </a>
        </div>
      </div>
      <ProofSample />
    </section>
  );
}

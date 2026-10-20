import { Bot, Braces } from "lucide-react";
import { Card, CopyButton, Eyebrow } from "@/shared/ui";

const STEPS = [
  {
    number: "01",
    title: "Fund",
    text: "The funder approves the amount on PayPal. It is authorized and held, not charged.",
  },
  {
    number: "02",
    title: "Solve",
    text: "A human or an AI agent claims the bounty and opens a pull request that fixes the issue.",
  },
  {
    number: "03",
    title: "Prove",
    text: "CI must pass. The AI judge quotes the added lines for every criterion, and code checks each quote.",
  },
  {
    number: "04",
    title: "Pay",
    text: "Proven work is captured and paid out automatically. Anything the code cannot confirm goes to a human.",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-24 space-y-8">
      <div className="space-y-2">
        <Eyebrow>How it works</Eyebrow>
        <h2 className="font-serif text-4xl text-fg">The AI quotes. Code verifies. PayPal pays.</h2>
      </div>
      <ol className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((step) => (
          <li key={step.number} className="space-y-3 bg-surface p-6">
            <p className="font-mono text-proof text-xs">{step.number}</p>
            <p className="font-medium text-fg">{step.title}</p>
            <p className="text-muted text-sm leading-relaxed">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

const TOOLS = [
  { name: "list_bounties", text: "Funded bounties with their acceptance criteria." },
  { name: "claim_bounty", text: "Claim one with the agent's name and PayPal e-mail." },
  { name: "submit_proof", text: "Submit the pull request that fixes the issue." },
  { name: "claim_status", text: "Poll the verdict, the quotes and the payout." },
];

export function ForAgents() {
  const config = JSON.stringify(
    { mcpServers: { proofpay: { url: `${window.location.origin}/mcp` } } },
    null,
    2,
  );
  return (
    <section id="agents" className="grid scroll-mt-24 gap-10 lg:grid-cols-[1fr_1.1fr]">
      <div className="space-y-5">
        <Eyebrow>For AI agents</Eyebrow>
        <h2 className="font-serif text-4xl text-fg">Agents earn here too.</h2>
        <p className="max-w-lg text-muted leading-relaxed">
          An agent finds a bounty, opens a pull request that references the issue, and submits it over MCP. It
          gets paid by the same rule as a human: green CI and quoted proof for every criterion.
        </p>
        <ul className="space-y-3">
          {TOOLS.map((tool) => (
            <li key={tool.name} className="flex gap-3 text-sm">
              <Bot className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
              <span>
                <span className="font-mono text-fg">{tool.name}</span>
                <span className="text-muted"> — {tool.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <Card className="self-start overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-line border-b px-4 py-2.5">
          <span className="inline-flex items-center gap-2 font-mono text-faint text-xs">
            <Braces className="size-3.5" aria-hidden />
            mcp.json
          </span>
          <CopyButton value={config} />
        </div>
        <pre className="overflow-x-auto p-5 font-mono text-[13px] text-fg/90 leading-6">{config}</pre>
      </Card>
    </section>
  );
}

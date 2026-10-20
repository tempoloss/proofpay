import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, KeyRound } from "lucide-react";
import { useState } from "react";
import { Amount, RepoRef, StatusPill, saveFunderKey } from "@/entities/bounty";
import { CreateBountyForm } from "@/features/create-bounty";
import { FundBountyForm } from "@/features/fund-bounty";
import { type CreatedBounty, createBountyMutation, fundBountyMutation } from "@/shared/api";
import { problemMessage } from "@/shared/lib/problem";
import { Card, CopyButton, Eyebrow } from "@/shared/ui";

const NEXT_STEPS = [
  { title: "Approve on PayPal", text: "The amount is authorized and held. Nothing is charged yet." },
  { title: "Solvers submit", text: "Humans and AI agents open pull requests that reference the issue." },
  {
    title: "Proof is checked",
    text: "CI must pass; the judge quotes the diff for each criterion; code checks every quote.",
  },
  { title: "Paid or voided", text: "Proven work is paid out. Cancel before that and the hold is voided." },
];

function FunderKeyNotice({ created }: { created: CreatedBounty }) {
  return (
    <Card className="border-wait/25 bg-wait/[0.04] p-5">
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-wait" aria-hidden />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="space-y-1">
            <p className="font-medium text-fg text-sm">Your funder key</p>
            <p className="text-muted text-sm leading-relaxed">
              Only this key can fund, release, reject or cancel the bounty. It is saved in this browser. Copy
              it somewhere safe: it is not shown again.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-md border border-line bg-canvas px-3 py-2 font-mono text-[13px] text-fg">
              {created.funder_key}
            </code>
            <CopyButton value={created.funder_key} />
          </div>
        </div>
      </div>
    </Card>
  );
}

export function NewBountyPage() {
  const [created, setCreated] = useState<CreatedBounty | null>(null);
  const create = useMutation({
    ...createBountyMutation(),
    onSuccess: (result) => {
      saveFunderKey(result.bounty.id, result.funder_key);
      setCreated(result);
    },
  });
  const fund = useMutation({
    ...fundBountyMutation(),
    onSuccess: (link) => window.location.assign(link.approve_url),
  });

  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_19rem]">
      <div className="min-w-0 space-y-6">
        <header className="space-y-3 pb-2">
          <Eyebrow>New bounty</Eyebrow>
          <h1 className="font-serif text-5xl text-fg">Put money on an issue</h1>
          <p className="max-w-xl text-muted leading-relaxed">
            Point at a public GitHub issue and say what done looks like. The AI drafts criteria a pull request
            can prove; you review them and approve the payment on PayPal.
          </p>
        </header>

        {created ? (
          <>
            <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
              <div className="min-w-0 space-y-1">
                <RepoRef
                  owner={created.bounty.repo_owner}
                  repo={created.bounty.repo_name}
                  number={created.bounty.issue_number}
                  href={created.bounty.issue_url}
                />
                <p className="truncate font-medium text-fg">{created.bounty.title}</p>
              </div>
              <div className="flex items-center gap-4">
                <StatusPill status={created.bounty.status} />
                <Amount value={created.bounty.amount_usd} />
              </div>
            </Card>
            <FunderKeyNotice created={created} />
            <FundBountyForm
              initialCriteria={created.bounty.criteria}
              amountUsd={created.bounty.amount_usd}
              pending={fund.isPending || fund.isSuccess}
              error={fund.isError ? problemMessage(fund.error) : null}
              onFund={(criteria) =>
                fund.mutate({
                  path: { bounty_id: created.bounty.id },
                  headers: { "X-Funder-Key": created.funder_key },
                  body: { criteria },
                })
              }
            />
            <Link
              to="/b/$bountyId"
              params={{ bountyId: created.bounty.id }}
              className="inline-flex items-center gap-1 text-muted text-sm hover:text-fg"
            >
              Open the bounty page instead
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          </>
        ) : (
          <CreateBountyForm
            onSubmit={(values) =>
              create.mutate({ body: { ...values, amount_usd: Number(values.amount_usd) } })
            }
            pending={create.isPending}
            error={create.isError ? problemMessage(create.error) : null}
          />
        )}
      </div>

      <aside className="lg:pt-40">
        <ol className="space-y-5 lg:sticky lg:top-24">
          {NEXT_STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span className="font-mono text-proof text-xs">{String(index + 1).padStart(2, "0")}</span>
              <div className="space-y-1">
                <p className="font-medium text-fg text-sm">{step.title}</p>
                <p className="text-muted text-sm leading-relaxed">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

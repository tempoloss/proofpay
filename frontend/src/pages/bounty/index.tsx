import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, SearchX } from "lucide-react";
import {
  Amount,
  ClaimList,
  CriteriaList,
  EventFeed,
  MoneyRail,
  RepoRef,
  StatusPill,
  useBounty,
  useFunderKey,
  VerdictList,
  VerdictSummary,
} from "@/entities/bounty";
import { FundBountyForm } from "@/features/fund-bounty";
import { FunderPanel } from "@/features/funder-actions";
import { SolvePanel } from "@/features/solve-bounty";
import { fundBountyMutation } from "@/shared/api";
import { problemCode, problemMessage } from "@/shared/lib/problem";
import { Alert, buttonVariants, Card, CardHeader, EmptyState, Skeleton } from "@/shared/ui";

const HOLD_CAPTION: Record<string, string> = {
  draft: "Not funded yet",
  awaiting_payment: "Waiting for PayPal approval",
  funded: "Held by PayPal",
  in_review: "Held by PayPal, under review",
  needs_human: "Waiting for the funder",
  released: "Captured, paying out",
  paid: "Paid to the solver",
  cancelled: "Hold released",
  expired: "Hold released",
};

function PageSkeleton() {
  return (
    <div className="space-y-8">
      <Skeleton className="h-28" />
      <Skeleton className="h-36 rounded-card" />
      <div className="grid gap-8 lg:grid-cols-[1fr_21rem]">
        <Skeleton className="h-80 rounded-card" />
        <Skeleton className="h-80 rounded-card" />
      </div>
    </div>
  );
}

export function BountyPage({ bountyId }: { bountyId: string }) {
  const bounty = useBounty(bountyId);
  const { key, forget } = useFunderKey(bountyId);
  const fund = useMutation({
    ...fundBountyMutation(),
    onSuccess: (link) => window.location.assign(link.approve_url),
  });

  if (bounty.isPending) return <PageSkeleton />;
  if (bounty.isError) {
    return problemCode(bounty.error) === "BOUNTY_NOT_FOUND" ? (
      <EmptyState
        icon={<SearchX />}
        title="Bounty not found"
        description="The link may be wrong, or the bounty was never created."
        action={
          <Link to="/" className={buttonVariants({ size: "sm" })}>
            Back to bounties
          </Link>
        }
      />
    ) : (
      <Alert title="Could not load the bounty">{problemMessage(bounty.error)}</Alert>
    );
  }

  const page = bounty.data;
  return (
    <div className="space-y-8">
      <Link to="/" className="inline-flex items-center gap-1.5 text-muted text-sm hover:text-fg">
        <ArrowLeft className="size-3.5" aria-hidden />
        Bounties
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-8">
        <div className="min-w-0 max-w-3xl space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <RepoRef
              owner={page.repo_owner}
              repo={page.repo_name}
              number={page.issue_number}
              href={page.issue_url}
            />
            <StatusPill status={page.status} />
          </div>
          <h1 className="text-balance font-semibold text-3xl text-fg tracking-tight">{page.title}</h1>
          <p className="text-muted leading-relaxed">
            <span className="text-faint">Done when </span>
            {page.done_when}
          </p>
        </div>
        <div className="space-y-1 text-right">
          <Amount value={page.amount_usd} size="lg" />
          <p className="font-mono text-faint text-xs">{HOLD_CAPTION[page.status] ?? page.status}</p>
        </div>
      </header>

      <Card className="px-6 py-5">
        <MoneyRail status={page.status} events={page.events} />
      </Card>

      <div className="grid gap-8 lg:grid-cols-[1fr_21rem]">
        <div className="min-w-0 space-y-8">
          {key && page.status === "draft" ? (
            <FundBountyForm
              eyebrow="Funder"
              initialCriteria={page.criteria}
              amountUsd={page.amount_usd}
              pending={fund.isPending || fund.isSuccess}
              error={fund.isError ? problemMessage(fund.error) : null}
              onFund={(criteria) =>
                fund.mutate({
                  path: { bounty_id: page.id },
                  headers: { "X-Funder-Key": key },
                  body: { criteria },
                })
              }
            />
          ) : page.verdict ? (
            <Card>
              <CardHeader
                eyebrow="Verdict"
                title="Every criterion, proven or not"
                actions={<VerdictSummary verdict={page.verdict} />}
              />
              <div className="space-y-1 px-5 py-4">
                <p className="pb-2 text-faint text-xs">
                  The judge quotes the pull request; code checks every quote against its added lines.
                </p>
                <VerdictList verdict={page.verdict} criteria={page.criteria} />
              </div>
            </Card>
          ) : (
            <Card>
              <CardHeader eyebrow="Criteria" title="What the pull request must prove" />
              <div className="p-5">
                <CriteriaList criteria={page.criteria} />
              </div>
            </Card>
          )}
        </div>

        <aside className="space-y-6">
          {key ? <FunderPanel bounty={page} funderKey={key} onForget={forget} /> : null}
          <SolvePanel bounty={page} />
          <Card>
            <CardHeader title="Solvers" />
            <div className="p-5">
              <ClaimList claims={page.claims} />
            </div>
          </Card>
          <Card>
            <CardHeader title="Activity" />
            <div className="p-5">
              <EventFeed events={page.events} />
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

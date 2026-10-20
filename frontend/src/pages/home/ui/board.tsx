import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Inbox } from "lucide-react";
import { useState } from "react";
import { BountyRow, type BountyStatus } from "@/entities/bounty";
import { listBountiesOptions } from "@/shared/api";
import { cn } from "@/shared/lib/cn";
import { problemMessage } from "@/shared/lib/problem";
import { Alert, buttonVariants, EmptyState, Eyebrow, Skeleton } from "@/shared/ui";

type Filter = "all" | "open" | "review" | "paid";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "review", label: "In review" },
  { key: "paid", label: "Paid" },
];

const FILTER_BY_STATUS: Partial<Record<BountyStatus, Filter>> = {
  funded: "open",
  in_review: "review",
  needs_human: "review",
  released: "review",
  paid: "paid",
};

export function Board() {
  const [filter, setFilter] = useState<Filter>("all");
  const bounties = useQuery({ ...listBountiesOptions(), refetchInterval: 10_000 });
  const visible = (bounties.data ?? []).filter(
    (bounty) => filter === "all" || FILTER_BY_STATUS[bounty.status] === filter,
  );

  return (
    <section id="board" className="scroll-mt-24 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <Eyebrow>Board</Eyebrow>
          <h2 className="font-serif text-4xl text-fg">Bounties</h2>
        </div>
        <div className="inline-flex rounded-lg border border-line bg-surface p-1" role="tablist">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={filter === item.key}
              onClick={() => setFilter(item.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-[13px] transition-colors",
                filter === item.key ? "bg-raised text-fg" : "text-muted hover:text-fg",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {bounties.isPending ? (
        <div className="space-y-3">
          {["a", "b", "c"].map((key) => (
            <Skeleton key={key} className="h-[108px] rounded-card" />
          ))}
        </div>
      ) : bounties.isError ? (
        <Alert title="Could not load bounties">{problemMessage(bounties.error)}</Alert>
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<Inbox />}
          title={filter === "all" ? "No bounties yet" : "Nothing here right now"}
          description="Post a bounty on any public GitHub issue. It shows up here once PayPal holds the funds."
          action={
            <Link to="/new" className={buttonVariants({ variant: "primary", size: "sm" })}>
              Post a bounty
            </Link>
          }
        />
      ) : (
        <div className="space-y-3">
          {visible.map((bounty) => (
            <BountyRow key={bounty.id} bounty={bounty} />
          ))}
        </div>
      )}
    </section>
  );
}

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, CircleX, ExternalLink, KeyRound, RotateCcw, Send } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import type { BountyView } from "@/entities/bounty";
import {
  cancelBountyMutation,
  decideBountyMutation,
  fundBountyMutation,
  getBountyQueryKey,
} from "@/shared/api";
import { problemMessage } from "@/shared/lib/problem";
import { Alert, Button, Card, CardHeader } from "@/shared/ui";

type Action = "release" | "reject" | "cancel";

const CONFIRM_LABEL: Record<Action, string> = {
  release: "Confirm: capture and pay",
  reject: "Confirm: reject the submission",
  cancel: "Confirm: cancel and void",
};

/** Once the money is captured, release can only resend the payout and cancel becomes a refund. */
const CAPTURED_CONFIRM_LABEL: Record<Action, string> = {
  release: "Confirm: send the payout",
  reject: CONFIRM_LABEL.reject,
  cancel: "Confirm: refund the captured money",
};

/** Funder controls; shown only in the browser that holds the funder key. */
export function FunderPanel({
  bounty,
  funderKey,
  onForget,
}: {
  bounty: BountyView;
  funderKey: string;
  onForget: () => void;
}) {
  const queryClient = useQueryClient();
  const [armed, setArmed] = useState<Action | null>(null);
  const captured = bounty.events.some((event) => event.kind === "captured");
  const path = { bounty_id: bounty.id };
  const headers = { "X-Funder-Key": funderKey };
  const decide = useMutation({
    ...decideBountyMutation(),
    onSuccess: (page) => queryClient.setQueryData(getBountyQueryKey({ path }), page),
  });
  const cancel = useMutation({
    ...cancelBountyMutation(),
    onSuccess: (page) => queryClient.setQueryData(getBountyQueryKey({ path }), page),
  });
  const checkout = useMutation({
    ...fundBountyMutation(),
    onSuccess: (link) => window.location.assign(link.approve_url),
  });
  const failed = decide.error ?? cancel.error ?? checkout.error;
  const busy = decide.isPending || cancel.isPending || checkout.isPending;

  useEffect(() => {
    if (!armed) return;
    const timer = setTimeout(() => setArmed(null), 4000);
    return () => clearTimeout(timer);
  }, [armed]);

  const run = (action: Action) => {
    if (armed !== action) {
      setArmed(action);
      return;
    }
    setArmed(null);
    if (action === "cancel") cancel.mutate({ path, headers });
    else decide.mutate({ path, headers, body: { decision: action } });
  };

  const actionButton = (
    action: Action,
    label: string,
    icon: ReactNode,
    variant: "proof" | "danger" | "secondary",
  ) => (
    <Button
      key={action}
      variant={armed === action ? "primary" : variant}
      className="w-full justify-start"
      disabled={busy}
      loading={(action === "cancel" ? cancel : decide).isPending && armed === null}
      onClick={() => run(action)}
    >
      {icon}
      {armed === action ? (captured ? CAPTURED_CONFIRM_LABEL : CONFIRM_LABEL)[action] : label}
    </Button>
  );

  const actions: ReactNode[] = [];
  if (bounty.status === "awaiting_payment") {
    actions.push(
      <Button
        key="checkout"
        variant="proof"
        className="w-full justify-start"
        loading={checkout.isPending || checkout.isSuccess}
        disabled={busy}
        onClick={() => checkout.mutate({ path, headers, body: { criteria: bounty.criteria } })}
      >
        <ExternalLink aria-hidden />
        Continue to PayPal
      </Button>,
    );
  }
  if (bounty.status === "needs_human") {
    actions.push(
      actionButton(
        "release",
        captured ? "Retry the payout" : "Release payment",
        <Send aria-hidden />,
        "proof",
      ),
    );
    if (!captured)
      actions.push(actionButton("reject", "Reject the submission", <CircleX aria-hidden />, "danger"));
  }
  const cancellable =
    bounty.status === "draft" ||
    bounty.status === "awaiting_payment" ||
    bounty.status === "funded" ||
    bounty.status === "needs_human";
  if (cancellable)
    actions.push(
      actionButton(
        "cancel",
        captured ? "Refund to me" : "Cancel the bounty",
        captured ? <RotateCcw aria-hidden /> : <Ban aria-hidden />,
        "secondary",
      ),
    );

  return (
    <Card>
      <CardHeader eyebrow="Funder" title="Your controls" />
      <div className="space-y-4 p-5">
        {actions.length > 0 ? (
          <div className="space-y-2">{actions}</div>
        ) : (
          <p className="text-muted text-sm">
            {bounty.status === "in_review"
              ? "Review in progress. You decide only if the proof is incomplete."
              : "Nothing left to decide."}
          </p>
        )}
        {bounty.status === "needs_human" ? (
          <p className="text-faint text-xs leading-relaxed">
            {captured
              ? "The money is captured but the payout did not arrive. Retry it (a failed payout is never sent twice) or refund the money to yourself."
              : "The proof is incomplete. Read the verdict, then release the payment or reject the submission."}
          </p>
        ) : null}
        {failed ? <Alert title="Action failed">{problemMessage(failed)}</Alert> : null}
        <div className="flex items-center justify-between gap-2 border-line border-t pt-4">
          <span className="inline-flex min-w-0 items-center gap-2 font-mono text-faint text-xs">
            <KeyRound className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate">key ••••{funderKey.slice(-4)}</span>
          </span>
          <button type="button" className="text-faint text-xs hover:text-fail" onClick={onForget}>
            Forget on this device
          </button>
        </div>
      </div>
    </Card>
  );
}

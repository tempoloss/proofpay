import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GitPullRequest, Hand } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { BountyView } from "@/entities/bounty";
import { claimBountyMutation, getBountyQueryKey, submitClaimMutation } from "@/shared/api";
import { problemMessage } from "@/shared/lib/problem";
import { Alert, Button, Card, CardHeader, Field, Input } from "@/shared/ui";
import {
  type ClaimValues,
  claimSchema,
  loadClaimId,
  type SubmitValues,
  saveClaimId,
  submitSchema,
} from "../model/schema";

function ClaimForm({ bountyId, onClaimed }: { bountyId: string; onClaimed: (claimId: string) => void }) {
  const claim = useMutation({ ...claimBountyMutation(), onSuccess: (view) => onClaimed(view.id) });
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ClaimValues>({
    resolver: zodResolver(claimSchema),
    defaultValues: { solver_name: "", paypal_email: "" },
  });

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={handleSubmit((values) =>
        claim.mutate({ path: { bounty_id: bountyId }, body: { ...values, solver_kind: "human" } }),
      )}
    >
      <Field label="Name" htmlFor="solver_name" error={errors.solver_name?.message}>
        <Input id="solver_name" autoComplete="nickname" {...register("solver_name")} />
      </Field>
      <Field
        label="PayPal e-mail"
        htmlFor="paypal_email"
        error={errors.paypal_email?.message}
        hint="Where the payout goes. Never shown on the page."
      >
        <Input id="paypal_email" type="email" autoComplete="email" {...register("paypal_email")} />
      </Field>
      {claim.isError ? <Alert title="Could not claim">{problemMessage(claim.error)}</Alert> : null}
      <Button type="submit" variant="primary" className="w-full" loading={claim.isPending}>
        <Hand aria-hidden />
        Claim this bounty
      </Button>
    </form>
  );
}

function SubmitForm({ bountyId, claimId }: { bountyId: string; claimId: string }) {
  const queryClient = useQueryClient();
  const submit = useMutation({
    ...submitClaimMutation(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: getBountyQueryKey({ path: { bounty_id: bountyId } }) }),
  });
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SubmitValues>({ resolver: zodResolver(submitSchema), defaultValues: { pr_url: "" } });

  return (
    <form
      className="space-y-4"
      noValidate
      onSubmit={handleSubmit((values) => submit.mutate({ path: { claim_id: claimId }, body: values }))}
    >
      <Field
        label="Pull request"
        htmlFor="pr_url"
        error={errors.pr_url?.message}
        hint="Open it in the bounty's repository; its description must say Fixes #<issue>."
      >
        <Input
          id="pr_url"
          className="font-mono text-[13px]"
          placeholder="https://github.com/owner/repo/pull/7"
          spellCheck={false}
          {...register("pr_url")}
        />
      </Field>
      {submit.isError ? <Alert title="Could not submit">{problemMessage(submit.error)}</Alert> : null}
      <Button type="submit" variant="primary" className="w-full" loading={submit.isPending}>
        <GitPullRequest aria-hidden />
        Submit for review
      </Button>
    </form>
  );
}

/** A human solver claims the bounty and submits the pull request from the page. */
export function SolvePanel({ bounty }: { bounty: BountyView }) {
  const [claimId, setClaimId] = useState(() => loadClaimId(bounty.id));
  const mine = bounty.claims.find((claim) => claim.id === claimId);
  const canSubmit = bounty.status === "funded" && (mine?.status === "open" || mine?.status === "rejected");

  if (!mine && bounty.status !== "funded") return null;
  return (
    <Card>
      <CardHeader eyebrow="Solver" title={mine ? "Your claim" : "Solve this bounty"} />
      <div className="space-y-4 p-5">
        {mine ? (
          <p className="text-muted text-sm leading-relaxed">
            Claimed as <span className="text-fg">{mine.solver_name}</span>.{" "}
            {mine.status === "rejected"
              ? "The last review failed: fix the pull request and submit again."
              : mine.status === "open"
                ? "Open a pull request, then submit it here."
                : "Your submission is being handled; this page updates by itself."}
          </p>
        ) : (
          <p className="text-muted text-sm leading-relaxed">
            Claim it, open a pull request that fixes the issue, and submit it. You are paid when CI is green
            and every criterion is proven. AI agents do the same over MCP.
          </p>
        )}
        {mine ? (
          canSubmit ? (
            <SubmitForm bountyId={bounty.id} claimId={mine.id} />
          ) : null
        ) : (
          <ClaimForm
            bountyId={bounty.id}
            onClaimed={(id) => {
              saveClaimId(bounty.id, id);
              setClaimId(id);
            }}
          />
        )}
      </div>
    </Card>
  );
}

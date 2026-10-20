import { zodResolver } from "@hookform/resolvers/zod";
import { Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import { Alert, Button, Card, CardHeader, Field, Input, Textarea } from "@/shared/ui";
import { type CreateBountyValues, createBountySchema } from "../model/schema";

const QUICK_AMOUNTS = ["10", "25", "50", "100"];

export function CreateBountyForm({
  onSubmit,
  pending,
  error,
}: {
  onSubmit: (values: CreateBountyValues) => void;
  pending: boolean;
  error: string | null;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<CreateBountyValues>({
    resolver: zodResolver(createBountySchema),
    defaultValues: { issue_url: "", amount_usd: "25", done_when: "" },
  });
  const amount = watch("amount_usd");

  return (
    <Card>
      <CardHeader eyebrow="Step 1 of 2" title="Describe the work" />
      <form className="space-y-6 p-5" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field label="GitHub issue" htmlFor="issue_url" error={errors.issue_url?.message}>
          <Input
            id="issue_url"
            className="font-mono text-[13px]"
            placeholder="https://github.com/owner/repo/issues/1"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={errors.issue_url ? true : undefined}
            {...register("issue_url")}
          />
        </Field>

        <Field
          label="Bounty"
          htmlFor="amount_usd"
          error={errors.amount_usd?.message}
          hint="Sandbox dollars. PayPal authorizes this amount now and captures it only after proof."
        >
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-40">
              <span className="pointer-events-none absolute inset-y-0 left-3 grid place-items-center font-mono text-faint">
                $
              </span>
              <Input
                id="amount_usd"
                inputMode="decimal"
                className="pr-12 pl-7 font-mono text-base tabular-nums"
                aria-invalid={errors.amount_usd ? true : undefined}
                {...register("amount_usd")}
              />
              <span className="pointer-events-none absolute inset-y-0 right-3 grid place-items-center font-mono text-[11px] text-faint">
                USD
              </span>
            </div>
            <div className="flex gap-1.5">
              {QUICK_AMOUNTS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setValue("amount_usd", value, { shouldValidate: true })}
                  className={
                    amount === value
                      ? "rounded-md border border-proof/40 bg-proof/10 px-2.5 py-1 font-mono text-proof text-xs"
                      : "rounded-md border border-line px-2.5 py-1 font-mono text-muted text-xs transition-colors hover:border-line-strong hover:text-fg"
                  }
                >
                  ${value}
                </button>
              ))}
            </div>
          </div>
        </Field>

        <Field
          label="Done when"
          htmlFor="done_when"
          error={errors.done_when?.message}
          hint="Plain words. The AI turns this and the issue into criteria a pull request can prove."
        >
          <Textarea
            id="done_when"
            rows={3}
            placeholder="divide(a, 0) returns None instead of raising, and a test covers it"
            aria-invalid={errors.done_when ? true : undefined}
            {...register("done_when")}
          />
        </Field>

        {error ? <Alert title="Could not create the bounty">{error}</Alert> : null}

        <div className="flex items-center justify-end gap-4 border-line border-t pt-5">
          <Button type="submit" variant="primary" size="lg" loading={pending}>
            {pending ? null : <Sparkles aria-hidden />}
            {pending ? "Reading the issue…" : "Draft criteria"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

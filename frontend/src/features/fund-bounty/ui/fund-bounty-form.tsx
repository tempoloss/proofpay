import { zodResolver } from "@hookform/resolvers/zod";
import { Lock, Plus, X } from "lucide-react";
import { useFieldArray, useForm } from "react-hook-form";
import { formatUsd } from "@/shared/lib/format";
import { Alert, Button, Card, CardHeader, Textarea } from "@/shared/ui";
import { type CriteriaValues, criteriaSchema, MAX_CRITERIA, nextCriterionId } from "../model/criteria";

export function FundBountyForm({
  initialCriteria,
  amountUsd,
  eyebrow,
  submitLabel,
  onFund,
  pending,
  error,
}: {
  initialCriteria: readonly { id: string; text: string }[];
  amountUsd: string;
  eyebrow?: string;
  submitLabel?: string;
  onFund: (criteria: CriteriaValues["criteria"]) => void;
  pending: boolean;
  error: string | null;
}) {
  const {
    register,
    control,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<CriteriaValues>({
    resolver: zodResolver(criteriaSchema),
    defaultValues: { criteria: initialCriteria.map(({ id, text }) => ({ id, text })) },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "criteria", keyName: "key" });

  return (
    <Card>
      <CardHeader eyebrow={eyebrow ?? "Step 2 of 2"} title="Review the criteria" />
      <form className="space-y-5 p-5" onSubmit={handleSubmit((values) => onFund(values.criteria))} noValidate>
        <p className="text-muted text-sm leading-relaxed">
          Each criterion must be provable from lines the pull request adds. The judge quotes those lines and
          code checks every quote. Edit, remove or add before you pay.
        </p>

        <ol className="space-y-3">
          {fields.map((field, index) => (
            <li key={field.key} className="grid grid-cols-[2.25rem_1fr_auto] items-start gap-2">
              <span className="pt-2.5 font-mono text-faint text-xs">{field.id}</span>
              <div className="space-y-1">
                <Textarea
                  rows={2}
                  className="min-h-0"
                  aria-label={`Criterion ${field.id}`}
                  aria-invalid={errors.criteria?.[index]?.text ? true : undefined}
                  {...register(`criteria.${index}.text`)}
                />
                {errors.criteria?.[index]?.text ? (
                  <p className="text-fail text-xs">{errors.criteria[index]?.text?.message}</p>
                ) : null}
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="mt-1 px-2"
                aria-label={`Remove ${field.id}`}
                disabled={fields.length === 1}
                onClick={() => remove(index)}
              >
                <X aria-hidden />
              </Button>
            </li>
          ))}
        </ol>

        <Button
          size="sm"
          variant="ghost"
          disabled={fields.length >= MAX_CRITERIA}
          onClick={() =>
            append({ id: nextCriterionId(getValues("criteria").map((criterion) => criterion.id)), text: "" })
          }
        >
          <Plus aria-hidden />
          Add criterion
        </Button>

        {errors.criteria?.root?.message ? (
          <p className="text-fail text-xs">{errors.criteria.root.message}</p>
        ) : null}
        {error ? <Alert title="PayPal checkout did not start">{error}</Alert> : null}

        <div className="flex flex-wrap items-center justify-between gap-4 border-line border-t pt-5">
          <p className="max-w-sm text-faint text-xs leading-relaxed">
            You approve the payment on PayPal. It is authorized now and captured only after the work is
            proven.
          </p>
          <Button type="submit" variant="proof" size="lg" loading={pending}>
            {pending ? null : <Lock aria-hidden />}
            {submitLabel ?? `Fund ${formatUsd(amountUsd)} with PayPal`}
          </Button>
        </div>
      </form>
    </Card>
  );
}

import { z } from "zod";

export const MAX_CRITERIA = 6;

export const criteriaSchema = z.object({
  criteria: z
    .array(
      z.object({
        id: z.string(),
        text: z
          .string()
          .trim()
          .min(1, "Write the criterion or remove it")
          .max(500, "Keep it under 500 characters"),
      }),
    )
    .min(1, "Keep at least one criterion")
    .max(MAX_CRITERIA, `At most ${MAX_CRITERIA} criteria`),
});

export type CriteriaValues = z.infer<typeof criteriaSchema>;

/** The next free id in the `c1, c2, …` sequence, never reusing a removed one's number below the max. */
export function nextCriterionId(ids: readonly string[]): string {
  const numbers = ids.map((id) => Number(/^c(\d+)$/.exec(id)?.[1] ?? 0));
  return `c${Math.max(0, ...numbers) + 1}`;
}

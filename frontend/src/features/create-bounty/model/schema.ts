import { z } from "zod";

export const MAX_BOUNTY_USD = 500;

export const createBountySchema = z.object({
  issue_url: z
    .string()
    .trim()
    .regex(
      /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/issues\/\d+$/,
      "Paste a GitHub issue URL, like https://github.com/owner/repo/issues/1",
    ),
  // A decimal string: the API takes money as text, never as a float.
  amount_usd: z
    .string()
    .trim()
    .regex(/^\d+(\.\d{1,2})?$/, "Dollars, up to two decimals")
    .refine((value) => Number(value) >= 1 && Number(value) <= MAX_BOUNTY_USD, {
      message: `Between $1 and $${MAX_BOUNTY_USD}`,
    }),
  done_when: z
    .string()
    .trim()
    .min(10, "Describe the finished state in at least 10 characters")
    .max(2000, "Keep it under 2000 characters"),
});

export type CreateBountyValues = z.infer<typeof createBountySchema>;

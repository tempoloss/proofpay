import { z } from "zod";

export const claimSchema = z.object({
  solver_name: z.string().trim().min(1, "Your name or handle").max(100, "Keep it under 100 characters"),
  paypal_email: z
    .string()
    .trim()
    .max(254)
    .regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, "The PayPal e-mail that receives the payout"),
});

export const submitSchema = z.object({
  pr_url: z
    .string()
    .trim()
    .regex(
      /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+$/,
      "A pull request URL, like https://github.com/owner/repo/pull/7",
    ),
});

export type ClaimValues = z.infer<typeof claimSchema>;
export type SubmitValues = z.infer<typeof submitSchema>;

/** Claims live in this browser so a solver can come back and submit later. */
const storageKey = (bountyId: string): string => `proofpay:claim:${bountyId}`;

export const saveClaimId = (bountyId: string, claimId: string): void => {
  localStorage.setItem(storageKey(bountyId), claimId);
};

export const loadClaimId = (bountyId: string): string | null => localStorage.getItem(storageKey(bountyId));

/**
 * Read models of a bounty. They come from the generated API client, so the
 * UI cannot drift from the OpenAPI document; only the names are local.
 */
import type { BountyCard, BountyPage, ClaimView, Verdict, VerdictItem } from "@/shared/api";

export type { BountyCard, BountyEvent, Criterion, Verdict, VerdictItem } from "@/shared/api";

export type BountyView = BountyPage;
export type Claim = ClaimView;
export type BountyStatus = BountyCard["status"];
export type VerdictState = VerdictItem["state"];
export type Outcome = Verdict["outcome"];
export type CiState = Verdict["ci"];

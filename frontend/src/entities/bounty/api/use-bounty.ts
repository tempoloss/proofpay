import { useQuery } from "@tanstack/react-query";
import { getBountyOptions } from "@/shared/api";
import { POLL_INTERVAL_MS, shouldPoll } from "../model/status";

/** The bounty page view, polled while the server is still moving it (payment, review, payout). */
export function useBounty(bountyId: string) {
  return useQuery({
    ...getBountyOptions({ path: { bounty_id: bountyId } }),
    refetchInterval: (query) =>
      query.state.data && shouldPoll(query.state.data.status) ? POLL_INTERVAL_MS : false,
  });
}

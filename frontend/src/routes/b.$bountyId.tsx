import { createFileRoute } from "@tanstack/react-router";
import { BountyPage } from "@/pages/bounty";

export const Route = createFileRoute("/b/$bountyId")({
  component: function BountyRoute() {
    const { bountyId } = Route.useParams();
    return <BountyPage bountyId={bountyId} />;
  },
});

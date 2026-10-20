import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Link, Outlet } from "@tanstack/react-router";
import { SiteLayout } from "@/pages/layout";
import { buttonVariants, EmptyState } from "@/shared/ui";

export interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => (
    <SiteLayout>
      <Outlet />
    </SiteLayout>
  ),
  notFoundComponent: () => (
    <EmptyState
      title="Nothing here"
      description="This page does not exist."
      action={
        <Link to="/" className={buttonVariants({ size: "sm" })}>
          Back to bounties
        </Link>
      }
    />
  ),
});

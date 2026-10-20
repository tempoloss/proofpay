import { createFileRoute } from "@tanstack/react-router";
import { NewBountyPage } from "@/pages/new-bounty";

export const Route = createFileRoute("/new")({ component: NewBountyPage });

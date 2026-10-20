import { format, formatDistanceToNowStrict } from "date-fns";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/** "25" or "25.00" → "$25.00". The API sends amounts as decimal strings. */
export const formatUsd = (amount: string | number): string => usd.format(Number(amount));

/** "3 minutes ago", in the browser's clock. */
export const formatRelative = (iso: string): string =>
  formatDistanceToNowStrict(new Date(iso), { addSuffix: true });

/** "20 Oct 2026, 14:05" in the browser's time zone. */
export const formatExact = (iso: string): string => format(new Date(iso), "d MMM yyyy, HH:mm");

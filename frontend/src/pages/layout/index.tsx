import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Wordmark } from "@/shared/ui";

const navLink =
  "rounded-md px-2.5 py-1.5 text-muted transition-colors hover:text-fg data-[status=active]:text-fg";

export function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <div className="ambient flex min-h-dvh flex-col bg-no-repeat">
      <header className="sticky top-0 z-30 border-line/70 border-b bg-canvas/75 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-5">
          <Link to="/" className="text-fg" aria-label="ProofPay home">
            <Wordmark />
          </Link>
          <nav className="flex items-center gap-1 text-sm max-sm:hidden">
            <Link to="/" activeOptions={{ exact: true }} className={navLink}>
              Bounties
            </Link>
            <Link to="/new" className={navLink}>
              Post a bounty
            </Link>
            <a href="/#agents" className={navLink}>
              For agents
            </a>
          </nav>
          <span className="ml-auto inline-flex items-center gap-2 rounded-full border border-wait/25 bg-wait/[0.06] px-3 py-1 font-mono text-[11px] text-wait uppercase tracking-wider">
            <span className="size-1.5 rounded-full bg-wait" aria-hidden />
            PayPal sandbox
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-5 pt-10 pb-24">{children}</main>
      <footer className="border-line border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-faint text-xs">
          <span>Sandbox only: no real money moves.</span>
          <span className="font-mono">AI quotes · code verifies · PayPal pays</span>
        </div>
      </footer>
    </div>
  );
}

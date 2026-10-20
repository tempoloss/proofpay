# ProofPay

Escrowed bounties for GitHub issues: PayPal holds the money, CI and an AI judge release it.

A funder puts a USD bounty on a GitHub issue. PayPal authorizes the amount but does not take it.
A solver, a person or an AI agent over MCP, opens a pull request. The money is captured and paid
out only when CI is green **and** an AI judge has confirmed every acceptance criterion with a
quote from the lines the pull request adds. Anything the code cannot prove goes to the funder.

Sandbox only: PayPal sandbox, USD, public GitHub repositories.
Demo target: [tempoloss/proofpay-demo](https://github.com/tempoloss/proofpay-demo).
Live demo and MCP endpoint: https://proof.an8kk.dev

## The rule: AI quotes, code verifies

The model is never trusted to decide. For each acceptance criterion it must return `met`/`not met`,
a **verbatim quote**, and the file the quote comes from. Code then checks the answer
(`backend/proofpay/modules/bounties/domain/rules.py`):

- `added_lines(diff)` parses the unified diff into the added lines (`+`, not `+++`) of each file.
  Removed lines and context lines are never evidence.
- `check_quotes` marks a criterion `met` only if its quote, after `strip()`, is at least 8
  characters long and is a substring of the added lines of the file the judge named. A quote may
  span several consecutive added lines of that file.
- A criterion that is missing from the answer, answered twice, or `met` with a quote that is not
  found becomes `unverified`. The judge can never produce `met` that the diff does not contain.
- `outcome` combines the verified items with the CI state:
  - CI not green, or any criterion `not_met` -> `fail` (claim rejected, bounty reopens);
  - otherwise any `unverified` -> `needs_human` (the funder decides);
  - otherwise `pass` -> the money moves.
- CI state comes from GitHub check runs of the PR head commit: no runs is `red`, any unfinished
  run is `pending` (re-checked every 30 s), all `success`/`skipped`/`neutral` is `green`.
- A diff longer than `MAX_DIFF_CHARS` (200,000 characters) is not sent to the model at all: the
  bounty goes to `needs_human`. So does any GitHub or model failure during review.

## Lifecycle and money flow

```mermaid
stateDiagram-v2
    [*] --> draft: create, AI drafts criteria
    draft --> awaiting_payment: fund, order created
    awaiting_payment --> draft: checkout abandoned
    awaiting_payment --> funded: approved and authorized
    draft --> cancelled: cancel
    awaiting_payment --> cancelled: cancel
    funded --> in_review: pull request submitted
    in_review --> funded: CI red or criterion not met
    in_review --> released: pass, authorization captured
    in_review --> needs_human: unverified or capture failed
    needs_human --> released: funder releases
    needs_human --> funded: funder rejects
    needs_human --> cancelled: cancel, authorization voided
    funded --> cancelled: cancel, authorization voided
    released --> paid: payout SUCCESS
    released --> needs_human: payout failed
    funded --> expired: authorization ending, voided
    in_review --> expired: authorization ending, voided
    paid --> [*]
    cancelled --> [*]
    expired --> [*]
```

1. **Create.** `POST /bounties` reads the issue from GitHub; the model drafts 2-6 criteria.
   The response carries a funder key, shown once. Only its SHA-256 is stored.
2. **Fund.** The funder edits the criteria (1-6) and `POST /bounties/{id}/fund` creates a PayPal
   order with `intent: AUTHORIZE`. The funder approves it on PayPal; PayPal redirects the browser
   to `/paypal/return`, which authorizes the order. The bounty is now `funded` and the money is held.
3. **Claim and submit.** The solver claims the bounty and submits a pull request URL. The PR must
   be in the bounty's repository and its body must reference the issue (`Fixes #N`).
   One pull request is in review at a time.
4. **Review.** A background job waits for CI, fetches the diff, asks the judge, verifies the quotes.
5. **Release.** On `pass` the authorization is captured, then one Payouts item is sent to the
   solver's PayPal e-mail; a job polls the batch every 30 s until `SUCCESS` (`paid`).
6. **Otherwise.** `fail` reopens the bounty for another attempt; `needs_human` waits for the funder
   (`decide`: `release` or `reject`). `cancel` voids an unclaimed authorization. A job runs every
   10 minutes and voids authorizations that end within 24 hours (`expired`).

## PayPal APIs used

All calls are in `backend/proofpay/integrations/paypal/client.py`, one long-lived `httpx` client.

| API | Endpoint | Purpose |
|---|---|---|
| OAuth 2.0 | `POST /v1/oauth2/token` (client credentials) | Access token, cached until 60 s before expiry |
| Orders v2 | `POST /v2/checkout/orders` | Create the order, `intent: AUTHORIZE`, `USD` |
| Orders v2 | `POST /v2/checkout/orders/{id}/authorize` | Hold the funds after the funder approves |
| Payments v2 | `POST /v2/payments/authorizations/{id}/capture` | Take the held money (`final_capture: true`) |
| Payments v2 | `POST /v2/payments/authorizations/{id}/void` | Release the hold on cancel or expiry |
| Payouts v1 | `POST /v1/payments/payouts` | Pay the solver by e-mail, one item per batch |
| Payouts v1 | `GET /v1/payments/payouts/{batch_id}` | Poll the batch and item status |

**Idempotency.** Every POST carries a `PayPal-Request-Id` derived from our own ids, never random:

| Call | Request id |
|---|---|
| create order | `order-{bounty_id}` |
| authorize | `auth-{bounty_id}` |
| capture | `capture-{bounty_id}` |
| void | `void-{bounty_id}` |
| payout | `payout-{claim_id}` (also used as `sender_batch_id`) |

A retry after a timeout, a crashed worker or a repeated job sends the same id, so PayPal replays
the first result instead of performing the action again. On our side the second line of defence is
the database: capture and payout run under a row lock on the bounty, the capture id and the payout
batch id are stored right after each call commits, and a bounty that already has either is never
captured or paid again (see Safety).

Sandbox only; production would use PayPal Commerce Platform for marketplace payouts.
`PROOFPAY_PAYPAL_ENV=live` makes the PayPal client refuse to be built
(`RuntimeError: live PayPal disabled`) unless `PROOFPAY_ALLOW_LIVE=true` is also set.
Errors are logged as PayPal `name` and `debug_id` only; response bodies and credentials are
never logged.

## AI

`backend/proofpay/integrations/llm/client.py` implements one port, `ask(system, prompt, schema)`,
and returns a validated Pydantic object or raises `LLMUnavailable`.

- Primary: Gemini through `google-genai` with `response_mime_type="application/json"`, the Pydantic
  class as `response_schema` and low thinking level. Model name: `PROOFPAY_LLM_MODEL`.
- Optional fallback: any OpenAI-compatible endpoint (`POST {base_url}/chat/completions`, JSON mode),
  used only when `PROOFPAY_FALLBACK_BASE_URL`, `PROOFPAY_FALLBACK_MODEL` and
  `PROOFPAY_FALLBACK_API_KEY` are all set. A backend that errors or returns JSON that does not
  validate is skipped.
- Two uses: drafting criteria from the issue and the funder's "done when" text, and judging a PR.
- Untrusted input: issue text, the "done when" text and diffs are written by strangers. Each is
  wrapped in a tagged data block, a closing tag inside the data is broken so it cannot end its own
  block, and the system prompt tells the model never to follow instructions found in that data.
  Even if a prompt injection succeeds, it cannot make a quote appear in the diff, and the quote
  check is code (`prompts.py`, `rules.py`).
- Prompts and keys are not logged.

## For agents: MCP

Endpoint: `/mcp` (streamable HTTP, stateless, JSON responses). Agent configuration:

```json
{"mcpServers": {"proofpay": {"url": "https://proof.an8kk.dev/mcp"}}}
```

| Tool | Arguments | Returns |
|---|---|---|
| `list_bounties` | none | Funded bounties: `id`, `issue_url`, `title`, `amount_usd`, `done_when`, `criteria` |
| `claim_bounty` | `bounty_id`, `agent_name`, `paypal_email` | `claim_id` |
| `submit_proof` | `claim_id`, `pr_url` | `status` (`submitted` once review has started) |
| `claim_status` | `claim_id` | `status`, `bounty_status`, `verdict` (per criterion: state, quote, file, reason), `events` |

Flow: `list_bounties` -> `claim_bounty` -> open a pull request in the bounty's repository with
`Fixes #N` in its body, a fix that satisfies every criterion, and a test -> `submit_proof` ->
poll `claim_status` every 10-30 s until `accepted` (paid) or `rejected` (read the verdict, fix,
submit again). `needs_human` means the funder decides. Errors reach the agent as
`"{CODE}: {detail}"`, for example `PR_NOT_LINKED` or `BOUNTY_NOT_OPEN`.

## For humans: HTTP API

Base path `/api/v1`; interactive docs at `/api/docs`. Errors are RFC 9457 problem documents
with `urn:proofpay:error:` types.

| Method | Path | Who | Body / notes |
|---|---|---|---|
| GET | `/bounties` | anyone | bounties past draft and payment stages |
| GET | `/bounties/{id}` | anyone | criteria, claims, verdict, audit events |
| POST | `/bounties` | funder | `{issue_url, amount_usd, done_when}`; returns `funder_key` once |
| POST | `/bounties/{id}/fund` | funder, `X-Funder-Key` | `{criteria: [{id, text}]}`; returns `{approve_url}` |
| POST | `/bounties/{id}/decide` | funder, `X-Funder-Key` | `{decision: "release" \| "reject"}`, only from `needs_human` |
| POST | `/bounties/{id}/cancel` | funder, `X-Funder-Key` | voids a held authorization |
| POST | `/bounties/{id}/claims` | solver | `{solver_name, solver_kind: "human" \| "agent", paypal_email}` |
| POST | `/claims/{id}/submit` | solver | `{pr_url}` |

`GET /paypal/return?token=...` and `GET /paypal/cancel?token=...` (outside `/api/v1`) are the
PayPal redirect targets. Amounts are 1 to `PROOFPAY_MAX_BOUNTY_USD` (default 500), two decimals.

```bash
BASE=https://proof.an8kk.dev/api/v1

# solver: claim a funded bounty (returns the claim id)
curl -sX POST "$BASE/bounties/$BOUNTY_ID/claims" \
  -H 'Content-Type: application/json' \
  -d '{"solver_name": "alice", "solver_kind": "human", "paypal_email": "alice@example.com"}'

# solver: submit the pull request (its body must contain "Fixes #1")
curl -sX POST "$BASE/claims/$CLAIM_ID/submit" \
  -H 'Content-Type: application/json' \
  -d '{"pr_url": "https://github.com/tempoloss/proofpay-demo/pull/3"}'

# funder: release a bounty the judge could not decide
curl -sX POST "$BASE/bounties/$BOUNTY_ID/decide" \
  -H "X-Funder-Key: $FUNDER_KEY" -H 'Content-Type: application/json' \
  -d '{"decision": "release"}'

# funder: cancel and void the hold
curl -sX POST "$BASE/bounties/$BOUNTY_ID/cancel" -H "X-Funder-Key: $FUNDER_KEY"
```

The web app (`/`, `/new`, `/b/{id}`) does the same for funders: it keeps the funder key in
`localStorage` and shows Release / Reject / Cancel on the bounty page while that key is present.

## Architecture

```
backend/proofpay/
  app.py            Litestar app (API + /paypal redirects), health checks, problem+json errors
  worker.py         procrastinate worker: review_claim, poll_payout, expire_due (queue "money")
  mcp_server.py     MCP server, own process, same services as the HTTP API
  cli.py            openapi <path>, bootstrap-db
  modules/bounties/ domain -> application -> infrastructure / presentation
  integrations/     paypal, github, llm: a Protocol port + one client each
  shared/           errors, clock, logging, DB base
frontend/           React 19, Vite, TanStack Router + Query, Tailwind 4; API client generated
                    from frontend/schema/openapi.json
deploy/             compose.prod.yaml, nginx.conf, web.Dockerfile, env.example
```

- PostgreSQL 17 is the only datastore; the job queue (procrastinate) lives in it too.
- `import-linter` contracts (`backend/pyproject.toml`): layers `modules.bounties` ->
  `integrations` -> `shared`; `shared` imports neither; the `domain` package imports no other
  layer and no integration; `presentation` reaches data only through `application`;
  `application` imports neither `infrastructure` nor `presentation`.
- The domain (state table, diff parsing, quote check, CI aggregation) is pure functions and
  dataclasses, covered by `backend/tests/unit/test_rules.py`.
- Every state change writes an audit event (`events` table) in the same transaction; the bounty
  page shows them as a timeline.

## Run locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/) with Python 3.14, [bun](https://bun.sh).

```bash
docker compose -f backend/deploy/compose.dev.yaml up -d    # Postgres 17 on localhost:5433

cd backend
uv sync
# put your variables in a file outside git (template: ../deploy/env.example; locally leave out
# POSTGRES_PASSWORD and PROOFPAY_DATABASE_URL, the default URL matches the dev compose file)
$EDITOR ../.env.local
uv run --env-file ../.env.local proofpay-cli bootstrap-db  # Alembic, then the job queue schema
uv run --env-file ../.env.local proofpay-api               # http://localhost:8000
uv run --env-file ../.env.local proofpay-worker            # review, payout polling, expiry
uv run --env-file ../.env.local proofpay-mcp               # http://localhost:8001/mcp

cd ../frontend
bun install
bun run dev                                                # http://localhost:5273
```

Variables (see `deploy/env.example`; every setting has the `PROOFPAY_` prefix, see
`backend/proofpay/settings.py`):

| Variable | Meaning |
|---|---|
| `PROOFPAY_DATABASE_URL` | Default matches the dev compose file |
| `PROOFPAY_PAYPAL_CLIENT_ID`, `PROOFPAY_PAYPAL_CLIENT_SECRET` | Sandbox REST app credentials |
| `PROOFPAY_PAYPAL_ENV`, `PROOFPAY_ALLOW_LIVE` | `sandbox` by default; live is refused without the flag |
| `PROOFPAY_GITHUB_TOKEN` | Optional; read-only token for public repositories (higher rate limit) |
| `PROOFPAY_GEMINI_API_KEY`, `PROOFPAY_LLM_MODEL` | Primary model |
| `PROOFPAY_FALLBACK_BASE_URL`, `PROOFPAY_FALLBACK_MODEL`, `PROOFPAY_FALLBACK_API_KEY` | Optional fallback model |
| `PROOFPAY_PUBLIC_URL` | Where PayPal sends the browser back (default `http://localhost:5273`) |
| `PROOFPAY_MAX_BOUNTY_USD`, `PROOFPAY_MCP_PORT` | Limits and the MCP port (default 500, 8001) |

The Vite dev server proxies `/api`, `/paypal` and `/mcp` to the local processes, so the PayPal
return URL works on `localhost:5273`.

Checks (the same as CI, `.github/workflows/ci.yml`):

```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run mypy proofpay
uv run pytest        # needs the dev Postgres; creates the proofpay_test database on first run

cd ../frontend
bun run check && bun run typecheck && bun run test && bun run build

bash scripts/check_leaks.sh   # scans the tree for forbidden tokens, prints "no leaks"
```

To regenerate the web client after an API change:
`cd backend && uv run proofpay-cli openapi ../frontend/schema/openapi.json`, then
`cd ../frontend && bun run api:generate`.

## Production

`deploy/compose.prod.yaml` runs Postgres, API, worker, MCP and a `web` container (static build
behind nginx) on one host. nginx serves the app and proxies `/api/` and `/paypal/` to the API and
`/mcp` to the MCP server without buffering. Only `127.0.0.1:8530` is published; TLS is terminated
in front of it. Secrets come from an env file (`/etc/proofpay/env` by default, see
`deploy/env.example`).

```bash
docker compose -f deploy/compose.prod.yaml run --rm api proofpay-cli bootstrap-db
docker compose -f deploy/compose.prod.yaml up -d
```

## Safety notes

- **Never pay twice.** Stable PayPal request ids (above); `capture` and `payout` run under
  `SELECT ... FOR UPDATE` on the bounty row; the capture id and the payout batch id are committed
  right after each PayPal call; a bounty already `released` with a payout batch, or `paid`, returns
  without touching PayPal; a payout that failed after capture is retried from `needs_human` only
  by the funder, and never re-sent if a batch already exists.
- **Jobs.** A job is deferred only after the commit it depends on, and a step already queued for
  the same claim is not queued twice. Stale jobs find a different status and exit.
- **Escalation.** Whatever the code cannot prove goes to `needs_human`: unverified quotes, an
  oversized diff, GitHub or model outages, a failed capture, a failed payout. Money does not move
  by default.
- **Funder key.** Random, shown once, stored only as SHA-256, compared in constant time.
- **PR checks.** The PR must belong to the bounty's repository and reference the issue
  (`#12` does not count for issue 1).
- **Secrets.** Held in `SecretStr`, never logged; the repository is scanned by
  `scripts/check_leaks.sh` in CI.

Not done: refunds of money that was already captured and a dispute process (a captured bounty
cannot be cancelled or rejected; a failed payout is resolved by the funder through
`needs_human`); payouts to anyone but the e-mail given at claim time; live PayPal.

## License

MIT, see [LICENSE](LICENSE).

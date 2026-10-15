# geopoliticai

An English-language geopolitical research assistant built on LangGraph.

## What it is

The API runs an orchestrator that routes each turn to one of three branches:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
                  \-> reporter -> END
```

Geopolitical turns are delegated to the nested expert. Other turns are answered
by the orchestrator's own general-assistant branch, without source citations.
Report requests pause at an outline the user approves, revises, or cancels by
typing a reply; the static frontend distinguishes the finished report, giving
it Download .md and Copy actions.

The expert remains separately available in LangGraph Studio and is a two-node
graph:

```text
START -> search_and_fetch -> answer -> END
```

`search_and_fetch` runs three batched Brave queries restricted to a curated set
of domains, fetches up to ten of those pages, and extracts article text with
trafilatura. `answer` sends the retrieved text to one streamed plain-text OpenAI
call. Search, extraction, and model failures are surfaced to the client; the
expert has no degraded or fabricated fallback.

Conversation threads are persisted by a required Postgres LangGraph
checkpointer. The API request body is exactly one of `{query, thread_id}` or
`{resume, thread_id}`, where the resume carries the reply to a paused outline;
both fields are normalized and capped at 2,000 characters. The frontend keeps
the thread id in `localStorage` across reloads and its **New chat** control
mints a new thread.

The API requires `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL`, and `JWT_SIGNING_KEY`.
Compose derives `DATABASE_URL` from `POSTGRES_PASSWORD`, gives Postgres a
`pg_isready` healthcheck, and starts the backend only after Postgres is healthy.
The app declares `psycopg[binary]` directly for the checkpointer; no system
`libpq` installation is required. There is no `prompt_logs` persistence path or
`database.py` module: Postgres is used for LangGraph checkpoints and,
through LangGraph's store, the deep forecaster's cached video notes.

The stream caps emitted answers at 50,000 characters, but `_generate` continues
draining an over-limit upstream stream before emitting the capped result so the
checkpoint can complete. Production nginx applies Basic Auth to `/admin/` and `/phoenix/`; the
API is guarded by bearer JWTs verified by `auth.py`; `AUTH_REQUIRED=true` fails closed when credentials are missing, while
the local development configuration remains unauthenticated.

The maintained application lives under `agentic_backend/`. `agentic_backend/README.md` documents setup,
the API contract, and the static English frontend; `agentic_backend/src/` is the Python
import root. The FastAPI app exposes `GET /api/health`,
`POST /api/run_pipeline/stream`, and `/` for the frontend, with no synchronous
pipeline route. The streaming endpoint emits SSE `progress`, `token`, `pause`,
`result`, and `error` events, with `result` carrying `kind` and `truncated`;
a paused turn ends with `pause` and no `result` until the user's reply
resumes it.

A second service, `web_backend/`, hosts the Django identity service: accounts
(allauth, email-only with mandatory verification), the admin, and the
application tables. Its dev port is `ACCOUNTS_PORT` (default 8083). From the
host, `make migrate-web` runs its migrations (always first, before anything in
`agentic_backend` touches the database), `make createsuperuser` creates an
admin user, and `make test-web-backend` runs its suite against the dev
Postgres. The two services share the database and the root `.env` but never
each other's code.

## Deploy order (three migration systems share one database)

Production runs these steps automatically, in this order, in `deploy/vps.py deploy`
(called by `.github/workflows/deploy.yml`); the list below is why the order matters
and what to run by hand in development.

Django's `migrate`, Alembic, and the checkpointer's `setup()` touch disjoint
parts of the schema, but the checkpointer uses `CREATE INDEX CONCURRENTLY`,
which cannot run inside a transaction — so the order is explicit and not
incidental:

0. on the deploy that first ships `0002_checkpointer_to_agentic`, stop the
   running `agentic-backend` first (`docker compose stop agentic-backend`):
   the old image has no `search_path`, so once the tables move it fails every
   query, and if it restarts its `setup()` recreates an empty set in `public`
   that the new image then refuses to boot over
1. `docker compose run --rm web-backend .venv/bin/python manage.py migrate`, then
   `docker compose run --rm web-backend .venv/bin/python manage.py createcachetable` —
   the `DatabaseCache` table allauth's rate limiter reads on the first login
   (the root `make migrate-web` target runs both)
2. `make migrate-agentic` — Alembic creates the `agentic` schema and relocates
   LangGraph's four checkpointer tables out of `public` into it (guarded both
   ways: on a fresh database it is all no-ops; when both copies exist it
   `RAISE`s instead of guessing)
3. start `agentic-backend` (its lifespan runs `checkpointer.setup()`; a startup
   assertion first refuses to boot if `public.checkpoints` still exists, with
   the message: "`public.checkpoints still exists, so the checkpointer schema
   has not been migrated. Run 'make migrate-agentic' BEFORE starting this
   service.`" — starting first builds an empty second set of tables in
   `agentic` and hides the real history)
4. start `frontend`

Do not add a migrate-on-start hook to the `web-backend` container: two
replicas would race. Before the Basic Auth cutover (`users-auth/07`), run the
pre-launch purge with a `pg_dump` in hand: `purge_prelaunch_threads --dry-run`,
read the count, then `--apply` — deleted checkpointer rows are recoverable only
from that dump.

**Operator-side spend caps (not code, and not optional):** configure hard
spend caps in the OpenAI and Brave dashboards, a credit limit on the
production OpenRouter key (it pays for the forecaster's seven council
seats), and a budget alert on a billed Gemini project, before going live —
they are the only control that still holds when the application-layer quota
(`DAILY_RESEARCH_TURNS` and its site-wide ceiling) is wrong. Keep the
OpenRouter balance positive: a negative balance returns 402, which would
drop all seven council seats, which fails the forecast. Record the configured figures
here next to the deploy order.

The chat SPA's build stage (`npm ci`) reaches a registry at deploy time, which
today's `COPY index.html` build never did. A registry outage, a yanked
transitive dependency or a Node EOL bump breaks only that stage — the
mitigation is not in the Dockerfile: **every release's `:<sha>` image stays in
the registry, and `rollback.yml` restarts the last good one.**

## Production deploy (OVH VPS)

Deploys are manual: Actions → **Deploy** → Run workflow on `main`. The workflow runs
every test job, pushes `ghcr.io/rafalsliwinski3991/geopoliticai-<service>:<sha>` and
`:latest`, copies the compose files and `deploy/vps.py` into
`/srv/geopoliticai/releases/<sha>/`, and runs `deploy/vps.py deploy`: `pg_dump` to
`/srv/backups/pre-<sha>-<UTC>.sql.gz`, Django `migrate` + `createcachetable`, Alembic,
`up --wait`; then it curls `https://politicalagent.eu/api/health` and records the
release (`releases.log`, `current`). The last five releases and their snapshots are kept.

### One-time VPS bootstrap (manual, in this order)

1. Install Docker Engine and the Compose plugin
   (https://docs.docker.com/engine/install/ubuntu/); the deploy script runs on
   the VPS's preinstalled `python3` — 3.9 or newer (the script uses
   `list[str]` annotations and `str.removesuffix`).
2. `sudo adduser --disabled-password --gecos '' deploy && sudo usermod -aG docker deploy`;
   `sudo install -d -o deploy -g deploy /srv/geopoliticai /srv/backups`;
   `sudo install -d /var/www/certbot`.
3. On your machine: `ssh-keygen -t ed25519 -N '' -C github-actions-deploy -f vps_deploy`.
   Append `vps_deploy.pub` to `/home/deploy/.ssh/authorized_keys`. In GitHub → Settings →
   Secrets → Actions add `VPS_HOST` (`politicalagent.eu`), `VPS_USER` (`deploy`),
   `VPS_SSH_KEY` (the contents of `vps_deploy`) and `VPS_KNOWN_HOSTS`
   (`ssh-keyscan -H politicalagent.eu`). Delete the local private key afterwards.
4. As `deploy`: `docker login ghcr.io -u rafalsliwinski3991` with a classic token that
   has only `read:packages`.
5. Write `/srv/geopoliticai/.env` by hand (`chmod 600`), from `.env.example`, with
   production values: `DJANGO_ALLOWED_HOSTS=politicalagent.eu,www.politicalagent.eu`,
   `DJANGO_CSRF_TRUSTED_ORIGINS=https://politicalagent.eu,https://www.politicalagent.eu`,
   `AUTH_USER`, `AUTH_PASSWORD`, and every key the API requires.
6. Before the first deploy (nginx cannot start without a certificate):
   `sudo snap install --classic certbot && sudo ln -sf /snap/bin/certbot /usr/bin/certbot`
   (the snap is certbot's recommended install and has `reconfigure`, added in 2.3.0),
   then `sudo certbot certonly --standalone -d politicalagent.eu -d www.politicalagent.eu`.
7. Run the first deploy. Then switch renewals to the nginx webroot, with no downtime:
   `sudo certbot reconfigure --cert-name politicalagent.eu --webroot -w /var/www/certbot --deploy-hook "docker exec geopoliticai-frontend-1 nginx -s reload"`,
   and confirm with `sudo certbot renew --dry-run`.
8. After the first deploy, open github.com → your profile → Packages and confirm the three
   `geopoliticai-*` packages are **private** and linked to this repository.

Phoenix is at `https://politicalagent.eu/phoenix/`, behind the same
`AUTH_USER`/`AUTH_PASSWORD` as `/admin/`.

### Rolling back

A deploy that fails after its files reach the VPS rolls itself back: it restores that
deploy's snapshot and restarts the previous release. For a bug found later, run
Actions → **Rollback** with the `target=` and `confirm=` values printed in the summary
of the deploy you want to undo. It restores the database to just before that deploy:
**everything written since is deleted**. Code and data go back together; there are no
reverse migrations.

Rehearse this once on purpose before real users arrive: deploy a commit whose
`/api/health` fails and watch the automatic rollback.

### Nightly off-site backup

`python3 deploy/vps.py backup` uploads a `pg_dump` to OVH Object Storage bucket `dramatic-wieman`
(Paris 3-AZ, `https://s3.eu-west-par.io.cloud.ovh.net`). One-time setup, as `deploy`:

1. Confirm in the OVH panel that the VPS is **not** in the Paris region.
2. Create an S3 user for the bucket and write `/srv/geopoliticai/backup.env` (`chmod 600`):
   `AWS_ACCESS_KEY_ID=…` and `AWS_SECRET_ACCESS_KEY=…` (the image is pinned by
   digest to aws-cli 2.22.35 for OVH compatibility; see `AWS_CLI` in `vps.py`).
3. Expire copies after 14 days: save
   `{"Rules":[{"ID":"expire-nightly","Status":"Enabled","Filter":{"Prefix":"nightly/"},"Expiration":{"Days":14}}]}`
   as `lifecycle.json` and run
   `docker run --rm --env-file /srv/geopoliticai/backup.env -v "$PWD:/w" amazon/aws-cli:2.22.35@sha256:6977c83ae3dc99f28fcf8276b9ea5eec33833cd5be40574b34112e98113ec7a2 s3api put-bucket-lifecycle-configuration --bucket dramatic-wieman --lifecycle-configuration file:///w/lifecycle.json --endpoint-url https://s3.eu-west-par.io.cloud.ovh.net --region eu-west-par`.
4. `crontab -e`:
   `15 3 * * * python3 /srv/geopoliticai/current/vps.py backup >> /srv/backups/nightly.log 2>&1 || curl -fsS https://hc-ping.com/<uuid>/fail`,
   replacing the URL with a dead-man's-switch ping you create on healthchecks.io (or
   similar). Without it, a backup that stops working — an expired S3 key, a full
   disk — goes unnoticed until a restore is needed.
5. After the first night, restore the newest copy into a scratch database once to
   prove it works.

### Queued email

Every email Django sends (allauth signup confirmation, password reset…) is stored
in the `emails_email` table and sent later by a batch job — nothing goes straight
out over SMTP. The batch sends at most 20 mails per run and never more than
`EMAIL_MAX_PER_HOUR` (default 100) in any 60 minutes; add the key to `.env` next
to the other `EMAIL_*` lines.

One-time VPS step, as `deploy` (`crontab -e`) — needed in the same deploy window
as enabling the queue, or verification mails will be stored but never sent:

```
* * * * * cd /srv/geopoliticai/current && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web-backend .venv/bin/python manage.py send_queued_emails >> /srv/backups/emails.log 2>&1
```

Check the OVH panel for the mailbox's real hourly limit and set
`EMAIL_MAX_PER_HOUR` accordingly (a forum post reports 200 per hour per mailbox).

### End-to-end tests

Playwright tests in `e2e/` drive the real app under Docker Compose at `http://localhost:8082`. Each chat
test spends one of the test user's 20 daily research units. Specs are plain English in
`e2e/test_specs/`; the tests in `e2e/tests/` are generated from them.

One-time setup:

1. Add `E2E_EMAIL` and `E2E_PASSWORD` to the root `.env`. Use letters and digits only in the password:
   the leak check compares it literally.
2. `make up`, then `docker compose up -d --force-recreate web-backend` so the container reads the new
   variables.
3. `make e2e-user` creates (or resets) the test user. It refuses unless `DEBUG` is on.
4. `cd e2e && npm ci && npx playwright install chromium`.

Running, from `e2e/`:

- `npx playwright test` runs the login setup and every test; results land in `test-results/` and
  `playwright-report/`.
- `npx playwright show-report` opens the HTML report.
- `bash check-no-password.sh` fails if the password reached any trace, result or report file.

If a run hits a 429 (quota spent), `make e2e-user` refills the user's quota.

In Claude Code, `/e2e new "<prompt>"`, `/e2e run [name]` and `/e2e update <name>` write, run and explain
tests from the specs.

### After the SEO launch (one-time, then upkeep)

User actions after the `seo-blog` deploy:

1. Create the `contact@politicalagent.eu` alias and confirm `blog@politicalagent.eu`
   exists — the blog's subscribe link and the privacy notice both name these addresses.
2. Paste the three post drafts from `docs/blog/` into `/admin/`: fill `summary`
   (≤160 characters), set `published_at`, and tick `is_published`.
3. Verify the domain in Google Search Console with a DNS TXT record and submit
   `https://politicalagent.eu/sitemap.xml`; import the property into Bing Webmaster
   Tools from Search Console.
4. Re-run the manual checks below after each nginx or settings change:

   - `curl -sI https://www.politicalagent.eu/x` → `301` to `https://politicalagent.eu/x`
   - `curl -sI https://politicalagent.eu/` shows `Strict-Transport-Security: max-age=31536000`
   - `curl -sI https://politicalagent.eu/chat` shows `X-Robots-Tag: noindex`
   - `https://politicalagent.eu/sitemap.xml` uses only `politicalagent.eu` URLs
   - Google Rich Results Test on one post after pasting it
   - Lighthouse shows no request to `fonts.googleapis.com`


:)

# JobPilot: Project Spec (for the AI coding assistant)

> Paste this whole file into your IDE assistant (Cursor / Claude Code / Copilot) as the first message, or save it in the repo root as `PROJECT_SPEC.md` (or `CLAUDE.md` / `.cursorrules`) and tell the assistant to read it. **Build one milestone at a time. Stop after each milestone, summarize what you did, and wait for me to confirm before starting the next.**

---

## 1. What we're building

A personal project (me + a few friends as users, not a public launch) that acts as an **inbox-aware job-search assistant** for students hunting internships and new-grad roles.

**Core loop:**
1. Read the user's Gmail (read-only) to detect **Online Assessments (OAs)** and **interview invitations**, extract the company, type, and deadline.
2. Send **Telegram** notifications with inline buttons: **Recur** and **Dismiss**. If the user taps Recur, remind them twice a day (10:00 and 19:00 in the user's local time) until they Dismiss, the deadline passes, or a completion email is detected.
3. Poll company career boards for new postings, match them against the user's resume and company preferences, and notify the user quickly when a relevant role drops.
4. When the user applies, detect the confirmation email, check the Sent folder for cold emails to that company, and if none exist, nudge the user with a LinkedIn search link and an LLM-drafted cold email.

**Phase 2 (NOT now):** Chrome extension for ATS autofill. Do not build or scaffold this yet.

## 2. Tech stack (use exactly this unless you find a blocking problem, then ask me)

- **Language:** Python 3.12+
- **API:** FastAPI + Uvicorn
- **DB:** Postgres (Supabase free tier in prod, Docker Postgres locally) with the `pgvector` extension
- **ORM/migrations:** SQLAlchemy 2.0 (async) + Alembic
- **Bot:** `python-telegram-bot` v21+ (async)
- **Scheduling:** a DB-driven "tick" worker (see section 6), not in-memory timers
- **Gmail:** `google-api-python-client`, `google-auth-oauthlib`
- **LLM:** Anthropic API (Claude) behind a thin `llm/` interface so the provider is swappable. Use a cheap, fast model for classification and extraction.
- **Embeddings:** behind an `embeddings/` interface (default: a hosted embedding API; keep dimension configurable)
- **HTTP client:** `httpx` (async)
- **Testing:** `pytest`, `pytest-asyncio`, `freezegun` (or `time-machine`)
- **Tooling:** `uv` or `pip`, `ruff`, `mypy`, `pre-commit`
- **Packaging/local dev:** Docker Compose (api, worker, postgres)
- **Onboarding UI:** minimal server-rendered pages (Jinja2) served by FastAPI. No separate frontend framework.

## 3. Repo structure

```
jobpilot/
├── README.md
├── PROJECT_SPEC.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── alembic/
├── src/jobpilot/
│   ├── config.py              # pydantic-settings, all env vars
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── api/
│   │   ├── main.py            # FastAPI app
│   │   ├── routes_auth.py     # Google OAuth flow
│   │   ├── routes_onboarding.py
│   │   └── templates/         # Jinja2 pages
│   ├── gmail/
│   │   ├── client.py          # build service, token refresh
│   │   ├── poller.py          # history.list incremental sync
│   │   └── parser.py          # headers/snippet/body extraction (in-memory only)
│   ├── classify/
│   │   ├── rules.py           # stage 1: cheap sender/keyword filter
│   │   ├── llm_classifier.py  # stage 2: confirm + extract structured fields
│   │   └── schemas.py         # pydantic output models
│   ├── bot/
│   │   ├── app.py             # telegram Application setup
│   │   ├── handlers.py        # /start, /link, /pause, /timezone, callbacks
│   │   └── messages.py        # message templates + inline keyboards
│   ├── reminders/
│   │   ├── scheduler.py       # tick loop
│   │   └── schedule_math.py   # next 10am/7pm in user tz (pure functions)
│   ├── jobs/                  # (Milestone 3+)
│   │   ├── sources/           # greenhouse.py, lever.py, ashby.py
│   │   ├── normalize.py
│   │   └── matcher.py
│   ├── resume/                # (Milestone 4)
│   ├── applications/          # (Milestone 5)
│   ├── llm/
│   ├── embeddings/
│   ├── security/
│   │   └── crypto.py          # Fernet encryption for refresh tokens
│   └── worker.py              # entrypoint: runs poller + reminder tick + job pollers
├── tests/
│   ├── unit/
│   ├── fixtures/emails/       # synthetic + anonymized sample emails
│   └── eval/
│       ├── labeled_emails.csv # hand-labeled set (I will fill this in)
│       └── run_eval.py        # prints precision/recall/F1 per class
└── scripts/
```

## 4. Data model (initial schema)

Use UUID primary keys, `created_at`/`updated_at` on everything. IANA timezone strings (e.g. `America/Chicago`), never UTC offsets.

- **users**: `id`, `telegram_chat_id` (unique, nullable until linked), `email`, `timezone` (IANA, default `America/Chicago`), `quiet_hours_start`, `quiet_hours_end`, `paused` (bool), `created_at`
- **gmail_accounts**: `id`, `user_id`, `google_email`, `refresh_token_encrypted`, `history_id`, `last_polled_at`, `status` (`active|needs_reauth|disabled`)
- **processed_emails**: `id`, `user_id`, `gmail_message_id` (unique per user), `thread_id`, `sender_domain`, `received_at`, `label` (`oa|interview|application_confirmation|rejection|other`), `confidence`. **No email bodies or subjects are stored.**
- **events**: `id`, `user_id`, `processed_email_id`, `kind` (`oa|interview`), `company`, `role_title` (nullable), `platform` (HackerRank, CodeSignal, HireVue, etc., nullable), `deadline_at` (timestamptz, nullable), `link` (nullable), `status` (`active|completed|expired|dismissed`)
- **reminders**: `id`, `event_id`, `user_id`, `state` (`awaiting_choice|recurring|dismissed|done`), `next_fire_at` (timestamptz, indexed), `last_sent_at`, `telegram_message_id`, `send_count`
- **companies**: `id`, `name`, `ats` (`greenhouse|lever|ashby|workday|other`), `board_token`, `domains` (text[]; email domains), `tags` (text[]; e.g. `autonomy`, `rideshare`, `fintech`), `careers_url`
- **user_company_prefs**: `user_id`, `company_id`, `status` (`watch|muted`)
- **job_postings**: `id`, `company_id`, `external_id`, `title`, `location`, `url`, `description_text`, `embedding` (vector), `first_seen_at`, `last_seen_at`, `is_open`. Unique on `(company_id, external_id)`.
- **resume_profiles**: `id`, `user_id`, `structured_json` (skills, domains, project themes, grad year, work auth), `embedding` (vector), `updated_at`
- **job_alerts**: `id`, `user_id`, `job_posting_id`, `score`, `sent_at`. Unique on `(user_id, job_posting_id)` for dedupe.
- **applications**: `id`, `user_id`, `company_id`, `job_posting_id` (nullable), `status` (`applied|oa|interview|offer|rejected`), `applied_at`, `confirmation_email_id`
- **outreach**: `id`, `application_id`, `kind` (`cold_email_detected|nudge_sent|draft_generated`), `contact_domain`, `created_at`

## 5. Non-negotiable engineering rules

1. **Privacy-minimal.** Only request `gmail.readonly`. Process email content in memory, persist only extracted fields (see `processed_emails`/`events`). Never log email bodies or subjects, even at DEBUG. Provide a `/delete_my_data` bot command that wipes all of a user's rows and revokes the Google token.
2. **Secrets.** Refresh tokens are encrypted at rest with Fernet (`crypto.py`). All secrets come from env vars via `config.py`. Commit only `.env.example`.
3. **Idempotency.** Re-polling the same email or re-running a tick must never create duplicate events, reminders, or notifications. Use unique constraints and `INSERT ... ON CONFLICT DO NOTHING`.
4. **Pure scheduling math.** `schedule_math.py` must be pure and fully unit-tested, including DST transitions (spring forward/fall back), users who change timezone, and the 7-day-before-deadline edge cases.
5. **Typed and linted.** Full type hints, `ruff` and `mypy --strict` passing, structured logging (JSON), no `print`.
6. **Tests ship with features.** Every milestone includes tests. Mock Gmail, Telegram, and the LLM in unit tests. Never hit real services in CI.
7. **Small commits.** One logical change per commit with a clear message. Don't commit generated junk.
8. **Ask before deviating.** If a requirement is ambiguous or you want a different library, ask first.

## 6. Reminder system design (important)

- When an `event` is created, send one Telegram message with the details and an inline keyboard:
  `[🔁 Recur] [✖ Dismiss]`
- `callback_data` format: `recur:<reminder_id>` and `dismiss:<reminder_id>`. Validate that the callback's chat belongs to the reminder's owner.
- **Recur** sets `state=recurring` and computes `next_fire_at` = the next 10:00 or 19:00 in the user's timezone (whichever comes first after now).
- **Dismiss** sets `state=dismissed`. No further messages.
- **Tick worker** runs every 60 seconds: `SELECT ... FROM reminders WHERE state='recurring' AND next_fire_at <= now() FOR UPDATE SKIP LOCKED`, sends the message (each recurring reminder message also has Dismiss, plus a "Mark done" button), then advances `next_fire_at` to the next slot, all in one transaction so a crash can't double-send.
- Stop conditions: user taps Dismiss or Mark done, the `deadline_at` has passed (mark event `expired`), or a completion signal is detected.
- Respect `quiet_hours` and `paused`.
- If a deadline is within 24 hours, include it in bold at the top of the message ("Due in 6 hours").
- Handle Telegram errors (bot blocked, chat not found) by pausing the user's reminders and logging.

## 7. Email classification design

Two stages:

1. **Stage 1, rules (`rules.py`):** cheap filter on sender domain and keywords. Known senders include hackerrank.com, codesignal.com, codility.com, hirevue.com, karat.com, and ATS notification domains (greenhouse, lever, myworkday, icims, ashbyhq, etc.), plus subject/snippet keywords such as "online assessment", "coding challenge", "interview", "schedule", "next steps", "HackerRank", "invitation". Anything that fails stage 1 is labeled `other` and never sent to the LLM (cost and privacy).
2. **Stage 2, LLM (`llm_classifier.py`):** send a trimmed version of the email (sender, subject, first ~1,500 chars of body) and require **strict JSON** output validated by pydantic:
   ```json
   {
     "label": "oa | interview | application_confirmation | rejection | other",
     "confidence": 0.0,
     "company": "string | null",
     "role_title": "string | null",
     "platform": "string | null",
     "deadline_iso": "ISO-8601 with timezone, or null",
     "link": "string | null"
   }
   ```
   Retry once on invalid JSON. Treat `confidence < 0.7` as `other` but log the count. Resolve relative deadlines ("within 7 days of this email") using the email's received date.

Build an **evaluation harness** (`tests/eval/run_eval.py`) that reads `labeled_emails.csv` (columns: `id, sender_domain, subject, body_snippet, true_label`) and reports per-class precision, recall, F1, and a confusion matrix. I will hand-label about 200 emails myself. This metric is a resume bullet, so make the harness clean.

## 8. Gmail polling design

- OAuth via `google-auth-oauthlib` web flow with scope `https://www.googleapis.com/auth/gmail.readonly` only. Store the encrypted refresh token and initial `historyId` (from `users.getProfile`).
- Every 3 to 5 minutes per account: `users.history.list(startHistoryId=..., historyTypes=['messageAdded'])`, fetch new messages (`format='full'` only for those passing stage 1 based on metadata headers first), classify, persist, update `historyId`.
- If `history.list` returns 404 (history expired), fall back to `messages.list` with `newer_than:7d`, then reset `historyId`.
- On `invalid_grant`, set `status=needs_reauth` and DM the user a re-auth link.
- Exponential backoff on 429/5xx. Respect per-user quota.

---

## 9. MILESTONES (build in order; stop after each)

### Milestone 0: Scaffold
- Create the repo structure above, `pyproject.toml`, `docker-compose.yml` (postgres with pgvector, api, worker), `.env.example`, `ruff`/`mypy`/`pre-commit` config, GitHub Actions CI (lint, type check, tests).
- `config.py` with pydantic-settings; `/healthz` endpoint.
- Alembic set up with the **initial schema for all tables in section 4** (create the tables now so later milestones don't need to rework the foundation).
- **Done when:** `docker compose up` starts everything, `/healthz` returns 200, `alembic upgrade head` works, CI is green.

### Milestone 1: Gmail connect + classifier
- Google OAuth routes (`/auth/google/start`, `/auth/google/callback`), Fernet token encryption.
- Gmail poller using the `history.list` flow in section 8, with the 404 fallback.
- Stage 1 rules + stage 2 LLM classifier + pydantic schemas + the `llm/` interface (with a fake implementation for tests).
- `processed_emails` and `events` persistence, idempotent.
- Eval harness plus 15 or more synthetic fixture emails covering OA, interview, confirmation, rejection, and noise.
- **Done when:** connecting a Gmail account results in new OA/interview emails producing `events` rows, and unit tests pass with mocked Gmail and LLM.

### Milestone 2: Telegram + reminders (this is the MVP)
- Telegram bot with `/start` (link account via a one-time code shown on the web page), `/timezone <IANA>`, `/pause`, `/resume`, `/delete_my_data`.
- Event notification message with Recur / Dismiss inline buttons and the callback handlers.
- `schedule_math.py` + tick worker as designed in section 6.
- Tests: DST spring-forward and fall-back, timezone change, idempotent double-tick, deadline expiry, quiet hours.
- **Done when:** a test OA email in my inbox triggers a Telegram message within about 5 minutes, tapping Recur produces reminders at 10:00 and 19:00 local time, and Dismiss stops them.

*(Stop here. I'll onboard a couple of friends before continuing.)*

### Milestone 3: Job board pollers
- Source adapters with a common interface (`fetch_jobs(company) -> list[NormalizedJob]`) for **Greenhouse** (`boards-api.greenhouse.io/v1/boards/{token}/jobs`), **Lever** (`api.lever.co/v0/postings/{company}`), and **Ashby** (public job board API).
- Seed script that loads a `companies.yaml` (name, ats, board_token, domains, tags). Start with about 40 companies, including autonomy and rideshare names (Waymo, Tesla, Uber, Lyft, Aurora, etc.) and others where the board token is verifiable.
- Diff logic: new postings insert with `first_seen_at`, disappeared postings flip `is_open=false`.
- Poll interval configurable (default 5 minutes), with jitter, per-host rate limiting, and ETag/If-Modified-Since where supported.
- Filter to internship/new-grad titles by configurable keywords.
- **Done when:** newly posted roles appear in `job_postings` with correct dedupe, and a log line records detection latency.

### Milestone 4: Resume profile + matching
- Resume upload (PDF/DOCX) on the onboarding page. Extract text in memory, use the LLM to produce a **structured profile JSON** (skills, domains, project themes, grad year, location prefs, work authorization). Let the user review and edit the extracted profile.
- Embed the profile and job descriptions (pgvector). Rank by cosine similarity, then apply **hard filters** (role type, grad year, location, work auth) and a user-configurable score threshold.
- Company-tag matching: map profile domains to `companies.tags` and auto-add matched companies as `watch` (the user can mute).
- Alert message: title, company, link, score, and a short LLM-written "why this matches you" blurb. Dedupe via `job_alerts`.
- **Done when:** a new matching posting triggers exactly one Telegram alert for each interested user.

### Milestone 5: Application tracker + cold-email nudge
- Detect `application_confirmation` emails and create/update `applications`.
- Search the user's Sent folder for messages to the company's known domains (`to:@domain`, within the last 60 days). Metadata only.
- If none are found, send a Telegram nudge with: a LinkedIn people-search deep link (company + "recruiter"), and an **LLM-drafted cold email** using the resume profile and role. Add inline buttons: "Show draft", "Mark as sent", "Snooze".
- `/applications` bot command listing statuses.
- **Done when:** applying to a role and receiving the confirmation email results in either "you already reached out" (silent) or a nudge with a draft.

### Milestone 6: Polish
- README with architecture diagram (Mermaid), setup instructions, a demo GIF, and a "Design decisions" section (privacy-minimal storage, idempotency, DST-safe scheduling, two-stage classification).
- Metrics page or script: emails processed, classifier precision/recall, alerts delivered, median detection latency.
- Quiet hours, per-company mute, and score threshold commands.

---

## 10. Explicitly out of scope
- Instagram story scraping (violates ToS, brittle). Instead provide a `/lead <url>` bot command so users can paste links manually.
- LinkedIn/Apollo scraping or API integration (use deep links only).
- Auto-subscribing to company email alerts.
- Workday scraping (maybe later).
- Mobile apps, billing, multi-tenant scaling, Google verification.

## 11. How I want you to work
1. Read this whole file first, then **propose a short plan for Milestone 0** and wait for my approval.
2. For each milestone: list the files you'll create or change, implement, run linters and tests, then give me a short summary and the commands to verify it works.
3. Keep PRs/commits small. Don't add dependencies that aren't justified.
4. If anything in this spec conflicts or is unclear, ask me instead of guessing.

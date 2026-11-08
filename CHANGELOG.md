# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-08

Accounts, Postgres with migrations, malware scanning, rate limits and an Azure deployment kit. Matching, parsing and the fact checker are the same as in 0.5.0, so the evaluation results haven't changed. `PIPELINE_VERSION` moves to 1.0.0 with the app version, and reports are the same as 0.5.0's apart from that string.

### Added

- Email and password accounts: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`, and `DELETE /api/v1/auth/me`, which deletes the account and everything it owns at once. Passwords need at least 12 characters and are stored as argon2id hashes. Errors never say whether an email has an account.
- Login sessions: random opaque tokens sent as `Authorization: Bearer`, stored only as SHA-256 hashes, ending after `SESSION_TTL_HOURS` (12 by default) or at logout.
- Ownership: every analysis endpoint needs a session and finds only the logged-in person's analyses. Anyone else's id is answered with 404.
- `GET /api/v1/analyses`: your analyses that haven't expired, newest first.
- `AUTH_MODE`: `required` (the default) or `disabled` for a single-user local demo.
- `python -m app.admin` to reset a password or delete an account by email.
- Alembic migrations (`alembic upgrade head`) with one initial revision for the whole schema, on SQLite and Postgres (psycopg 3). `DB_AUTO_MIGRATE` runs them at startup, by default only outside production. `python -m app.storage.migrations` prints where the database stands.
- Upload scanning with ClamAV (`SCANNER=clamav`) through clamd's INSTREAM command over TCP, with no extra dependency. An infected file is refused with 422 and nothing is stored. When the scanner can't be reached, uploads are refused with 503 (fail closed), and `/readyz` reports the API as not ready.
- In-memory rate limits per account and per client address for login and registration, analyses, suggestions and exports, answered with 429 and `Retry-After`.
- Security headers on every response: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, a Content-Security-Policy that allows nothing for JSON and a matching one for `/docs`, `Cache-Control: no-store` for the API, and `Strict-Transport-Security` in production.
- `TRUSTED_PROXIES` for reading the client address from `X-Forwarded-For`.
- `APP_ENV=production` checks: it refuses to start with SQLite, without `sslmode=require` on the database URL, with `AUTH_MODE=disabled`, with `CORS_ORIGINS=*`, with migrations pending, or without scanning unless `ALLOW_UNSCANNED_UPLOADS=true`, which logs a warning at every start.
- The Streamlit screen has login and registration, Log out, and "Delete my account and data" with a confirmation step. The token is kept only in the tab's session state.
- docker compose runs the API, the screen, Postgres and ClamAV, with login and scanning on.
- The API image's entrypoint runs `alembic upgrade head` when `RUN_MIGRATIONS=true`.
- `infra/azure/main.bicep`: Log Analytics, a Container Apps environment, Postgres Flexible Server with TLS required, the API with a ClamAV sidecar, the screen and a migration job. `docs/deploy-azure.md` walks through it with az CLI commands.
- Release workflow: a `v*` tag runs CI, then pushes the API (also with matching by meaning, tagged `-ml`) and screen images to ghcr.io. A manual workflow deploys a tag to Azure, signing in with OpenID Connect.
- CI runs the database tests and `alembic upgrade head` against Postgres, runs the screen tests with Streamlit, and the Docker smoke test registers, logs in and uses the token.
- `CHANGELOG.md` and `docs/demo-script.md`.

### Changed

- Database tables are created by the migrations instead of `create_all`. A SQLite file from 0.5.0 or earlier is upgraded in place: its analyses are kept for the local account that `AUTH_MODE=disabled` uses, and expire as before.
- Logs carry user ids, never emails, passwords or tokens. Request logs name the matched route's template instead of the URL as sent, and error tracebacks are logged without the error's message, which a library may fill with user input.
- An unexpected error is answered with a JSON 500 that names the request id.

### Not in this release

- No email is sent, so there is no address verification and no password reset by email.
- Rate limits are counted by each API process, so they are only correct with one replica.
- No single sign-on.

## [0.5.0] - 2026-11-08

### Added

- More role header layouts: dates on the next line, title and employer on separate lines, several titles under one employer, "Client:" and "Role:" lines. A city, state, country or "Remote" after the employer is dropped.
- Roles and degrees read from resumes that have no experience or education heading.
- Degree and certification requirements checked against the education and certification lines, and version requirements ("Angular 12 or later") against the versions in work bullets.
- The skill catalog grows from 107 to 328 skills.
- `python -m evals.run --data-dir` measures any labeled set, and a held-out set written without access to the app.

### Changed

- PDF lines that wrap are joined to the line above them, and a bold or dated line starts a new one.
- More job-description headings are recognized, and pay, benefit, legal and logistics lines are dropped with or without a heading.
- The test PDF builder embeds its font, so en dashes reach the app as written.

## [0.4.0] - 2026-11-08

### Added

- A hand-labeled evaluation set: 12 fictional resumes, 8 job descriptions, 16 pairs with 176 requirement labels, and 100 fact-check cases (60 development, 40 held out).
- `python -m evals.run`, which measures role and date extraction, requirement extraction and priorities, statuses, gap recall, the false proven rate, evidence recall and the fact checker across two PDF layouts and DOCX, and writes `evals/results/REPORT.md`.
- A CI check that fails when a metric drops below its threshold.

## [0.3.0] - 2026-11-08

### Added

- An optional Claude job-description parser behind the same interface as the rules, with checks on everything it returns and a fallback to the rules.
- Rewrite suggestions from Claude for the bullets that support a requirement, each passed through a deterministic fact checker that discards any rewrite adding a number, date, name, tool, certification or bigger claim. A cap per analysis bounds cost.
- Accepting and rejecting suggestions, correcting lines the app read wrongly, gap questions for missing requirements, and a single-column Word export with a list of every change.
- Versioned prompts and token usage in the logs.

## [0.2.0] - 2026-11-08

### Added

- Each role's title, employer and dates, and total years of experience with overlapping roles counted once.
- Years requirements checked against the role dates, including years with one skill.
- Optional matching by meaning with sentence-transformers (search, then rerank) and the `adjacent` status.
- Measurable results found in bullets.
- A Streamlit screen, docker compose, and an optional CPU-only ML image.

## [0.1.0] - 2026-11-07

### Added

- PDF and DOCX extraction that keeps sections, pages and bullet boundaries.
- A rule-based job-description parser that labels each line required, preferred or context.
- A 107-skill catalog with exact matching that avoids hits on common words.
- A report that links each requirement to resume evidence or marks it as a gap, with direct, partial, gap and not-assessed statuses.
- A FastAPI service with storage, deletion, 24-hour expiry and upload limits.
- Tests, strict type checking, linting, and CI with a Docker smoke test.

[1.0.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/compare/02c3195...v1.0.0
[0.5.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/commit/02c3195
[0.4.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/commit/6b763ac
[0.3.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/commit/8582174
[0.2.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/commit/9d13871
[0.1.0]: https://github.com/rahulmurarisetty/resume-evidence-matcher/releases/tag/v0.1.0

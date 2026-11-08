# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-08

Accounts, Postgres with migrations, malware scanning, rate limits and an Azure deployment kit, and the rest of the project's specification: consent, section order advice, metric questions, a downloadable match report, an accessibility pass, and document quality and a human rating sheet in the evaluation. Three reading fixes, found during a demo on one held-out example, change parsing; the fact checker is the same as in 0.5.0. `PIPELINE_VERSION` moves to 1.0.0 with the app version. Every development-set number is the same as in 0.5.0. On the held-out set, roles found rise from 77.8% to 83.3% and extraction precision from 93.6% to 95.7%, and that set is no longer fully unseen.

### Added

- Consent. `POST /api/v1/analyses` needs `consent=true` (422 `consent_required` otherwise, before anything is read). The consent time and the notice's version (`consent_v1`) are stored with the analysis, in new columns added by migration 0002, and returned in its `consent` field. `GET /api/v1/consent` returns the notice, built from the server's settings. `llm_consent` (default false) decides whether Claude may see the person's text: without it the rules read the job description even when Claude is on, and `POST .../suggestions` answers 409 `llm_consent_required`.
- Section order advice in the report (`section_advice`): bullets that prove more requirements than the first two of their role, projects that alone show a required skill, and, as a suggestion only, a skills section below experience when the job names many tools. It never changes the resume.
- Metric questions: up to five experience bullets with no measurable result, those that support required requirements first, get "How many, how much, how fast or how often? Add a number only if you know it." They come with the gap questions (`kind` "metric") and are answered at `PUT .../gap-answers/{question_id}`.
- The match report: `GET .../report.html` and `GET .../report.md`, owner only and counted against the export limit, with coverage, every requirement with its status in words and its evidence, the advice, the questions and answers, the terms noticed, the warnings and a note that employers use different systems and criteria. The HTML is accessible on its own and loads nothing; its style is allowed by hash in its Content-Security-Policy.
- `employment_terms` in the job: W2, 1099, C2C, corp to corp, third-party agencies, work authorization, visa sponsorship and citizenship lines, listed as "Terms noticed in the posting" in the screen and the report and never scored.
- `client` on each role, read from "Client:" lines.
- The screen shows the consent notice with a required box and, when Claude is on, an optional one; the employer systems note; the advice, terms and metric questions; and the two report downloads. Each error is written next to the input that caused it.
- The Word export sets its language (en-US) and title.
- The evaluation measures document quality (every resume exported, read back and checked for tables, text boxes, images, headers, footers, columns and real styles), with new floors in `thresholds.json`. `python -m evals.rating_sheet` and `python -m evals.rating_summary` write and summarize a sheet for a person to rate the evidence; it hasn't been rated. `--llm` saves each candidate with an empty `manual_review` field, and the report explains the hallucination rate and how to run it with your own key.
- `evals/baselines/holdout.json` keeps the blind v0.4 and v0.5 held-out runs, and the held-out report shows them next to the v1.0 run with a note that the set is no longer fully unseen.
- README sections on specification coverage and accessibility.

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

- Role headers: a name that ends with a company suffix (Pvt. Ltd., Inc., LLC, Technologies, Solutions and the like) is the employer, never the title, and a "Client:" line is the role's client, never its title or employer. Before, a "Client:" line was read as the employer.
- Job descriptions: employment-terms lines are no longer requirements, and intro sentences ("We are looking for a hands-on X to join our team", "In this role you will ...") are context, never required. The same rules apply to the Claude parser's output.
- `GET .../gap-questions` returns each question with an `id`, a `kind` and, for metric questions, the `span_id` and `line`; `requirement_id`, `requirement_text`, `priority` and `status` can be null for a metric question. `PUT .../gap-answers/{id}` takes that `id`.
- The Word export uses a resume layout: capitals with a rule under section headings, dates on a right-aligned tab, bold role, degree and label text, tight single spacing on Letter paper.
- The screen's headings go in order, and statuses read "Status: Proven" rather than a bold word.
- Database tables are created by the migrations instead of `create_all`. A SQLite file from 0.5.0 or earlier is upgraded in place: its analyses are kept for the local account that `AUTH_MODE=disabled` uses, and expire as before.
- Logs carry user ids, never emails, passwords or tokens. Request logs name the matched route's template instead of the URL as sent, and error tracebacks are logged without the error's message, which a library may fill with user input.
- An unexpected error is answered with a JSON 500 that names the request id.

### Not in this release

- No email is sent, so there is no address verification and no password reset by email.
- Rate limits are counted by each API process, so they are only correct with one replica.
- No single sign-on.
- Not run here: Claude (needs an API key), matching by meaning with the real models (needs the model download), the human rating of evidence and screen-reader testing (need a person).

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

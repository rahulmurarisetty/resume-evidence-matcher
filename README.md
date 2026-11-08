# Resume evidence matcher

Upload a resume and paste a job description. For every requirement in the job description, the app shows which resume lines prove it, which requirements have no proof, and what to do next. It also says which lines to move up, asks for missing numbers you know, and lists contract terms such as "Only W2" apart from the requirements. With a Claude key and your consent it suggests clearer wording for the bullets that prove a requirement, and a rule-based fact checker throws away any suggestion that adds a fact. You fix lines the app read wrongly, accept the rewrites you want, and download a plain Word file and a match report. It never invents skills, employers, dates or numbers.

Employers use different applicant tracking systems and different criteria, so there is no universal "ATS score", and the app doesn't produce one or predict any employer's decision. This is a tool for a person improving their own application. It doesn't rank or screen candidates. Each person agrees to a short notice before uploading, logs in to their own account and sees only their own analyses, every upload is scanned for malware before it is read (when the server runs ClamAV, as docker compose and the Azure template do), and everything stored expires after 24 hours or when the person deletes it.

[![CI](https://github.com/rahulmurarisetty/resume-evidence-matcher/actions/workflows/ci.yml/badge.svg)](https://github.com/rahulmurarisetty/resume-evidence-matcher/actions/workflows/ci.yml)

## What it does

1. You log in and read a short notice: what is stored, for how long, who can see it, whether uploads are scanned and, only when Claude is on, which text goes to Anthropic. You tick the box to agree (required) and, if you want rewrite suggestions, a second box for Claude (optional).
2. You upload a resume (PDF or Word) and paste a job description. ClamAV scans the file before anything reads it.
3. The app reads the resume and splits it into sections (summary, experience, skills, education), keeping every bullet and the page it came from.
4. It reads each job's title, employer, client (for consultants) and dates, adds up your years of experience, and marks bullets with a measurable result such as "40+" or "5 hours to 90 minutes".
5. It reads the job description and pulls out each requirement, labeling it required, preferred or a job duty. Benefits, the company intro and legal boilerplate are skipped. Intro sentences ("We are looking for a hands-on data engineer to join our team") are job duties, never required. Employment terms ("Only W2 candidates", "No visa sponsorship") are listed apart as terms noticed in the posting and never score anyone.
6. For each requirement it finds the skills named in it and looks for them in the resume. Requirements that ask for years are checked against the role dates, and degree or certification requirements against the education and certification lines.
7. If matching by meaning is on, it also looks for resume lines that say the same thing in other words.
8. Each requirement gets a result and a next step: proven in work experience, only listed in the skills section, related but worth checking, missing, or needs a person to check.
9. It advises on order, without changing anything: a bullet that proves more requirements than the first two of its role, a project that alone shows a required skill, and, as a suggestion only, a skills section below experience when the job names many tools.
10. With Claude on and your consent, Claude reads the job description instead of the rules. Every requirement it returns must appear word for word in the job description, or it is dropped. If Claude fails, the rules take over and the report says so.
11. For a requirement the resume supports, you can ask for rewrites of the bullet that supports it. Claude suggests up to two, and the fact checker discards any that add a number, date, name, tool, certification or claim the bullet doesn't make.
12. You accept or reject each suggestion, fix any line the app read wrongly, and answer a question for each missing requirement ("Have you used dbt? If yes, where, and what did you build with it?") and for up to five work bullets with no number ("How many, how much, how fast or how often? Add a number only if you know it."). Answers are kept with the analysis and never put into the resume.
13. You download a single-column Word file (your lines in their original order with your corrections and accepted rewrites, and a list of every change) and a match report as HTML or Markdown.

Here is the sample data engineer resume checked against the sample data engineer job (both fictional, in `samples/`). This is exact matching with the rule-based parser, which is what you get without the ml extra and without a Claude key:

| Job requirement | Type | Result | What the app found |
| --- | --- | --- | --- |
| Strong Python and SQL | Required | Proven | Experience bullets: "Wrote Python data-quality checks..." and "...ran a monthly session on SQL performance tuning." |
| Hands-on experience with PySpark on Databricks | Required | Proven | Experience bullet: "Built PySpark jobs on Databricks that load claims..." |
| 5+ years of experience in data engineering | Required | Proven | Two dated roles, Jun 2019 to Feb 2022 and Mar 2022 to present, add up to about 7.5 years (in November 2026). Next step: check that enough of that time is the kind of work the job asks for. |
| Comfortable with Git and CI/CD practices | Required | Only listed | Both appear only in the skills line "Cloud and tools: AWS, Git, CI/CD, Docker, Kubernetes". Next step: if you used them at a job, add a bullet that says where. |
| Experience with dbt | Preferred | Missing | Not in the resume. Next step: leave it out unless it's true. |
| Mentor two junior engineers and review their code | Job duty | Needs a check | Names no skill, so exact matching can't assess it. |

Across all six required items, five are proven (the three above, plus Snowflake and ETL on AWS) and one is only listed.

With matching by meaning on, the models compare a duty such as "Mentor two junior engineers and review their code" with every resume line. If a line such as "Reviewed pull requests for two junior engineers..." scores above the threshold, the duty is marked adjacent and the next step quotes that line and asks you to confirm it. The real models don't run in CI, so this README doesn't show their scores.

The fact checker is deterministic, so its verdicts can be shown exactly. These are its real results for rewrites of the sample bullet "Scheduled and monitored 40+ Airflow DAGs, adding SLA alerts that reduced missed morning loads from weekly to roughly once a quarter." The rewrites were written by hand for this table. No model output appears in this README, because no real API calls were made while building v0.3 or any later version.

| Candidate rewrite | Verdict | What the checker found |
| --- | --- | --- |
| Orchestrated 40 or more Airflow DAGs with SLA alerts, cutting missed morning loads from weekly to roughly once a quarter. | Kept | Nothing new: "40 or more" is "40+" and "cutting" is the same kind of result as "reduced". |
| Monitored 40+ Airflow DAGs with SLA alerts. | Kept | Nothing new. Trimming is allowed. |
| Orchestrated 400+ Airflow DAGs with SLA alerts, cutting missed morning loads from weekly to roughly once a quarter. | Discarded | The number "400+" isn't in the original line. |
| Led a team of 4 that scheduled 40+ Airflow and Prefect DAGs with SLA alerts. | Discarded | "Led" claims more responsibility, "4" is a new number and "Prefect" is a new product name. |
| Scheduled 40+ Airflow DAGs across the company, eliminating missed morning loads. | Discarded | "across the company" and "eliminating" widen the claim. |

What it never does: add skills, jobs, dates or numbers the person doesn't have, fill in a number for a metric question, put an unchecked rewrite in front of the person, change or store the uploaded file, move a line of the resume, score anyone on employment terms, show a fake "ATS match %", or rank one candidate against another.

## Status

Version 1.0 (see the [changelog](CHANGELOG.md) and the [roadmap](#roadmap)). 1.0 adds what a shared deployment needs: accounts, Postgres with migrations, malware scanning, rate limits, security headers and a kit for deploying to Azure. It also completes the project's specification (see [Specification coverage](#specification-coverage)): consent before an upload, section order advice, metric questions, a downloadable match report, an accessibility pass, document quality in the evaluation, and three reading fixes found during a demo on one held-out example. Those fixes left every development-set number where it was; on the held-out set they raise roles found from 77.8% to 83.3%, and the set is no longer fully unseen (see [Held-out results](#held-out-results)). The fact checker is the same as in 0.5. What works today:

- PDF and DOCX extraction that keeps each heading, bullet and line with its section and page. Wrapped bullets and paragraphs come back whole, and a bold line or a short line with a date range after a full-width line starts a new line of its own. Word skills tables are read row by row.
- Role parsing: title, employer, start and end month for each job, in many layouts ("Title, Employer | dates", "Employer: Title", "Employer - Title", the title and employer on separate lines, the dates on the next line, several titles under one employer, "Company:" and "Role:" lines). A name that ends with a company suffix ("Pvt. Ltd.", "Inc.", "LLC", "Technologies", "Solutions") is the employer, never the title, and a "Client:" line is kept as the role's client, never its title or employer. A city, state, country or "Remote" after the employer is dropped. A resume without an experience heading has its roles read from the lines with date ranges. "Present", "Current", "Now" and "Till date" mark current roles. Total years of experience count overlapping jobs once.
- Education entries (degree, school, year), also without an education heading, and measurable results (counts, percentages, money, durations, multipliers) in work bullets.
- A rule-based job-description parser that labels each line required, preferred or context, and picks up the title, seniority and years asked for. It knows the common headings ("What you'll need", "Bonus points", "Our stack"), treats any short line ending in a colon or written in capitals as a heading, and drops benefit, pay, legal and logistics lines (salary ranges, 401(k), PTO, equal opportunity, background checks, how to apply) with or without a heading. Employment terms (W2, 1099, C2C, corp to corp, third-party agencies, work authorization, visa sponsorship, citizenship or green card) are listed in `employment_terms` instead, and intro sentences ("We're hiring a...", "Join our team as...", "In this role you will...") are context.
- A Claude-based job-description parser behind the same interface, with checks on everything it returns and a fallback to the rules. Skills outside the catalog are kept as free-text skills and matched as whole phrases.
- Exact skill matching against a catalog of 328 skills, with care for terms that are also ordinary words (REST, Excel, React, Go, R, Jest, Helm, Swift). A requirement for "GitHub Actions" asks for GitHub Actions, not also for Git.
- Degree and certification requirements ("Bachelor's degree in Computer Science or a related field", "AWS Certified Solutions Architect") checked against the education and certification lines.
- Years requirements: "5+ years of experience" is checked against the role dates, and "7+ years with Java" against the roles that mention Java. Version requirements ("Angular 12 or later") need a version in the bullet.
- Optional matching by meaning with sentence-transformers: an embedding model finds candidate lines and a cross-encoder reranks them. A requirement with no exact evidence but a related work bullet is marked `adjacent`.
- A report linking every requirement to resume evidence or marking it as a gap, with a next step written for that requirement, and deterministic section order advice that never changes the resume.
- Rewrite suggestions from Claude for the bullets that support a requirement, each one passed through a deterministic fact checker, with a cap per analysis. They need the person's consent for Claude, given per analysis.
- Corrections of lines the app read wrongly, a gap question for each missing or adjacent requirement, a metric question for up to five work bullets with no number, a Word export and a list of every change.
- A downloadable match report (`report.html` and `report.md`): coverage, each requirement with its status in words and its evidence, the advice, the questions and your answers, the terms noticed and the warnings. The HTML is accessible on its own and loads nothing.
- Consent: an analysis is made only with `consent=true`, and its consent time and text version are stored with it. Claude sees a person's resume and job text only with `llm_consent=true`.
- Email and password accounts. Passwords are hashed with argon2id, login sessions are random tokens stored only as SHA-256 hashes, and errors never say whether an email has an account. Each person sees only their own analyses, and deleting an account deletes everything it owns at once.
- Postgres through psycopg 3 (SQLite for local work and tests), with Alembic migrations. A database file from 0.5 or earlier is upgraded in place.
- Malware scanning of every upload with ClamAV. When the scanner can't be reached, uploads are refused rather than let through.
- Rate limits per account and per client address, security headers on every response, and production checks that refuse to start with unsafe settings.
- A FastAPI service with storage, deletion, automatic expiry after 24 hours, JSON logs and upload limits.
- A Streamlit screen with login, the consent notice and its boxes, and download buttons, reviewed for accessibility (see [Accessibility](#accessibility)), and a docker compose file that runs it with the API, Postgres and ClamAV.
- A Bicep template and a step-by-step guide for Azure Container Apps, a release workflow that publishes the images to ghcr.io, and a workflow that deploys a release. See [Deployment](#deployment).
- An evaluation against a hand-labeled set of fictional resumes and job descriptions (`python -m evals.run`), with its results in [evals/results/REPORT.md](evals/results/REPORT.md) and a check in CI that fails when a metric drops below its threshold. It also measures document quality: every resume is exported to Word and read back, and the file is checked for tables, text boxes, images, headers, footers and columns. The same runner measures any other labeled set with `--data-dir`, and `python -m evals.rating_sheet` writes a sheet for a person to rate the evidence (not filled in yet). See [Evaluation](#evaluation).
- 935 tests, 934 passing here: one runs only against Postgres (CI's postgres job), and the screen tests need Streamlit and are skipped without it. 98% line coverage of `app/`, strict type checking of `app/` and `evals/`, CI that also runs the database tests against Postgres and smoke-tests the image on Postgres, and a Dockerfile with an optional CPU-only ML build. No test calls the Anthropic API.

## Quick start

### With Docker

You need Docker with Compose, and about 4 GB of free memory for ClamAV.

```bash
docker compose up --build
```

Open http://localhost:8501, choose Create account, then use the screen. The first start takes a few minutes while the images build and ClamAV loads its virus signatures, and the screen appears once the API reports ready. This runs the stack the way production runs it: login is required, ClamAV scans every upload, Postgres stores the data, and the API container runs the database migrations once at start. The API and its interactive docs are at http://localhost:8000/docs (use Authorize with the token from `POST /api/v1/auth/login`).

`docker compose down` stops the stack and keeps the data, and `docker compose down -v` also deletes the database, the ClamAV signatures and the model cache. The Postgres password has a local-only default; set `POSTGRES_PASSWORD` in `.env` to change it.

For matching by meaning, build the API with the ml extra:

```bash
INSTALL_ML=true docker compose up --build
```

In Windows PowerShell, set the variable first: `$env:INSTALL_ML = "true"; docker compose up --build`. That installs PyTorch from the CPU-only index, so the image never pulls CUDA libraries, but it is still much larger than the default image. The first start downloads the two models into the `model-cache` volume. Compose passes `ANTHROPIC_API_KEY` and `LLM_ENABLED` from your shell or the local `.env` file to the API, so Claude stays off unless you set a key.

The API image also runs on its own, with SQLite inside the container and scanning off:

```bash
docker build -t resume-evidence-matcher .
docker run -p 8000:8000 resume-evidence-matcher
```

### Without Docker

Python 3.11 or newer.

macOS or Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload
```

This keeps its data in SQLite (`data/app.db`) and creates the tables on the first start. Login is required here too: open http://localhost:8000/docs, register and log in there, or start the Streamlit screen below. For a quick single-user try without accounts, start it with `AUTH_MODE=disabled` (production refuses that setting). Scanning is off by default outside Docker. To scan uploads, run ClamAV in Docker with its port open on this machine only, and point the API at it:

```bash
docker run -d --name clamav -p 127.0.0.1:3310:3310 clamav/clamav:1.4
SCANNER=clamav uvicorn app.main:create_app --factory --reload
```

### Adding matching by meaning

Install the ml extra. It brings in sentence-transformers and PyTorch.

```bash
pip install -e ".[dev,ml]"
```

On Linux without a GPU, install the CPU-only PyTorch first, so pip doesn't download several GB of CUDA libraries:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev,ml]"
```

With `SEMANTIC_MATCHING=auto` (the default), the app turns matching by meaning on when sentence-transformers is installed. The first start downloads the two models from Hugging Face, about 180 MB in all, and later starts load them from the local cache. Each report says which mode it used, in `matching_mode` and in `pipeline_version` ("1.0.0-semantic" or "1.0.0-exact").

### Turning on Claude

Claude reads job descriptions and writes rewrite suggestions. It is off until you give the API a key. Copy `.env.example` to `.env` in the project folder and set the key there:

```bash
cp .env.example .env
# then edit .env:
# ANTHROPIC_API_KEY=your key
```

`.env` is listed in `.gitignore` and `.dockerignore`, so the key stays on your machine. Never put a real key in `.env.example`, a commit, an issue or a log. The app keeps the key in a secret field that doesn't print, and never writes it to logs, errors or reports.

With `LLM_ENABLED=auto` (the default), Claude is on when a key is set and off when it isn't. `LLM_ENABLED=on` stops the app at startup if the key is missing, and `off` ignores any key. Without Claude, the rule-based parser reads the job description and asking for suggestions returns 409 with a message that says how to turn them on. Everything else works the same. With Claude on, it still sees a person's text only for an analysis made with the Claude box ticked (`llm_consent=true`); otherwise the rules read the job description and suggestions answer 409 `llm_consent_required`.

Each report says which parser read the job description, in `job_parser`:

```json
"job_parser": {
  "name": "claude",
  "prompt_version": "jd_parse_v1",
  "model": "claude-haiku-5-5",
  "fallback_reason": null,
  "dropped_requirements": 0
}
```

When Claude was tried and failed, `name` is "rules" and `fallback_reason` is `timeout`, `api_error` or `invalid_output`.

### Streamlit screen

The screen talks to the API over HTTP, so start the API first.

```bash
pip install -e ".[ui]"
streamlit run ui/app.py
```

It opens at http://localhost:8501. Set `API_URL` if the API isn't at http://localhost:8000. It starts with a login screen, with a tab for creating an account, unless the API runs with `AUTH_MODE=disabled`. The session token lives only in the screen's session state for that browser tab: it never goes into a URL, a cookie or a log, and closing the tab forgets it. When the API stops accepting the token (it expired after `SESSION_TTL_HOURS`, or you logged out elsewhere), the screen goes back to the login screen.

After logging in, the screen shows the consent notice above the upload form, with a required box and, when Claude is on, an optional box for Claude. The results start with a note that employers use different systems and criteria, then coverage for each priority and one card per requirement with its status in words, its evidence and next step. Cards for requirements the resume supports have a "Suggest rewrites" button, and each suggestion shows your line and the rewrite side by side with Accept and Reject buttons. Cards for missing requirements show their question with an answer box. After the cards come the section order advice, the terms noticed in the posting, and the questions about bullets without a number. Below the report are a form for fixing lines the app read wrongly, the list of your changes, "Download Word file" and the two match report downloads, and a button that deletes the analysis from the server. The sidebar has Log out and "Delete my account and data", which asks for confirmation before it deletes anything.

## Try it

The `samples/` folder has two fictional resumes (as PDF and DOCX) and two job descriptions. Every endpoint under `/api/v1` except register and login needs a session token, so create an account and log in first:

```bash
API=http://localhost:8000
ACCOUNT='{"email": "you@example.com", "password": "at least twelve characters"}'
curl -X POST $API/api/v1/auth/register -H "Content-Type: application/json" -d "$ACCOUNT"
TOKEN=$(curl -s -X POST $API/api/v1/auth/login -H "Content-Type: application/json" -d "$ACCOUNT" \
  | python -c "import json, sys; print(json.load(sys.stdin)['token'])")

curl $API/api/v1/consent -H "Authorization: Bearer $TOKEN"   # the notice to agree to
curl -X POST $API/api/v1/analyses -H "Authorization: Bearer $TOKEN" \
  -F resume=@samples/generated/jordan_example_data_engineer.pdf \
  -F "job_description=<samples/jobs/data_engineer.txt" \
  -F consent=true
```

`@` uploads the resume as a file. `<` sends the job description's text as a form field. `consent=true` says the person agrees to the notice; without it the API answers 422 `consent_required` and reads nothing. Add `-F llm_consent=true` to let Claude read the job description and, later, the bullets picked for rewrites. In Windows PowerShell, call `curl.exe` instead of `curl`, use a backtick for line breaks, and set the token with `$TOKEN = (Invoke-RestMethod -Method Post -Uri "$API/api/v1/auth/login" -ContentType "application/json" -Body $ACCOUNT).token`.

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Create an account: `{"email": "...", "password": "..."}`. The password needs at least 12 characters. Answers 202 with the same message whether or not the email already had an account. |
| POST | `/api/v1/auth/login` | Log in. Returns a `token` to send as `Authorization: Bearer <token>`, its `expires_at` and the account. A wrong password and an unknown email get the same 401. |
| POST | `/api/v1/auth/logout` | End this session. The token stops working at once. |
| GET | `/api/v1/auth/me` | The logged-in account: id, email, creation time and `auth_mode`. |
| DELETE | `/api/v1/auth/me` | Delete the account and every analysis, suggestion, correction and answer it owns, at once. Every session of the account ends. |
| GET | `/api/v1/consent` | The consent notice to show before an upload, built from this server's settings: `version`, `points`, the `checkbox` label, and `llm_available`, `llm_points` and `llm_checkbox` for Claude. |
| GET | `/api/v1/analyses` | Your analyses that haven't expired, newest first, with the job title and the coverage of required items. |
| POST | `/api/v1/analyses` | Match a resume (`resume` file) against a job description (`job_description` text). Needs `consent=true` (422 `consent_required` otherwise). `llm_consent=true` lets Claude read this person's job text and, later, the bullets picked for rewrites; it is stored as false when Claude is off. Returns the report, an id and `consent` (`given_at`, `version`, `llm`). |
| GET | `/api/v1/analyses/{id}` | Fetch a stored report, with its consent. |
| DELETE | `/api/v1/analyses/{id}` | Delete a report and everything stored with it. |
| POST | `/api/v1/analyses/{id}/suggestions` | Ask Claude for rewrites. Send `{"requirement_ids": ["r6"]}` for chosen requirements, or no body for every eligible requirement that has none yet. Returns the suggestions that passed the fact checker, how many were discarded, which requirements were skipped and why, and the remaining allowance. 409 when Claude is off (`llm_disabled`), when the analysis was made without `llm_consent=true` (`llm_consent_required`) or when the allowance is used up. |
| GET | `/api/v1/analyses/{id}/suggestions` | Every suggestion with its status (`proposed`, `accepted`, `rejected`), source line, prompt version and model. |
| POST | `/api/v1/analyses/{id}/suggestions/{sid}/accept` | Accept a suggestion. One accepted rewrite per line. |
| POST | `/api/v1/analyses/{id}/suggestions/{sid}/reject` | Reject a suggestion, or undo an accept. |
| GET | `/api/v1/analyses/{id}/spans` | The lines the app read, each with its current text and whether it was corrected. |
| PATCH | `/api/v1/analyses/{id}/spans/{span_id}` | Correct a line the app read wrongly: `{"text": "..."}`. Sending the original text removes the correction. |
| GET | `/api/v1/analyses/{id}/gap-questions` | One question per missing or adjacent requirement (`kind` "gap"), then up to five about work bullets with no number (`kind` "metric", with `span_id` and `line`), each with its `id` and any answer. |
| PUT | `/api/v1/analyses/{id}/gap-answers/{question_id}` | Save an answer to the question with that `id` (the requirement id for a gap question, `metric-<span id>` for a metric one): `{"answer": "..."}`. An empty answer removes it. |
| GET | `/api/v1/analyses/{id}/export.docx` | The Word file with corrections and accepted rewrites applied. |
| GET | `/api/v1/analyses/{id}/export/changes` | Every change in the export: `before`, `after` and `kind` (`correction` or `rewrite`). |
| GET | `/api/v1/analyses/{id}/report.html` | The match report as one accessible HTML page with no scripts and no outside files. Counts against the export limit. |
| GET | `/api/v1/analyses/{id}/report.md` | The same report as Markdown. Counts against the export limit. |
| POST | `/api/v1/extract` | Show the text the app read from a resume, with sections and pages. Nothing is stored. |
| GET | `/healthz`, `/readyz` | Liveness, and readiness: the database and, with `SCANNER=clamav`, ClamAV both answer. No login needed. |

Without a valid token the API answers 401 with `WWW-Authenticate: Bearer`. An analysis that belongs to someone else is answered with 404, like one that doesn't exist, so ids reveal nothing. Errors always have the form `{"error": {"code": "...", "message": "..."}}`. Uploads can also get 422 `malware_detected` when ClamAV flags the file, 503 `scanner_unavailable` when scanning is on and ClamAV can't be reached, and 429 `rate_limited` with a `Retry-After` header (see [Security and privacy](#security-and-privacy)).

With an analysis id from the first call:

```bash
AUTH="Authorization: Bearer $TOKEN"
curl -X POST $API/api/v1/analyses/$ID/suggestions -H "$AUTH" \
  -H "Content-Type: application/json" -d '{"requirement_ids": ["r6"]}'
curl -X PATCH $API/api/v1/analyses/$ID/spans/s3 -H "$AUTH" \
  -H "Content-Type: application/json" -d '{"text": "Data engineer with six years of experience."}'
curl -o resume.docx -H "$AUTH" $API/api/v1/analyses/$ID/export.docx
curl -o match-report.html -H "$AUTH" $API/api/v1/analyses/$ID/report.html
```

The suggestions call needs an analysis made with `-F llm_consent=true` on a server with Claude on.

Analyses made by v0.2 didn't store their lines, so their spans, export and suggestions return 409 with a message asking to run the analysis again, and they get no metric questions. Analyses stored before the consent migration (0002) have no consent time or version and no consent for Claude, so suggestions stay off for them until they expire.

## Example output

From the sample data engineer resume against the sample data engineer job, with exact matching:

```json
"pipeline_version": "1.0.0-exact",
"matching_mode": "exact",
"job_parser": { "name": "rules", "prompt_version": null, "model": null, "fallback_reason": null, "dropped_requirements": 0 },
"coverage": {
  "required": { "total": 6, "direct": 5, "partial": 1, "gap": 0, "adjacent": 0, "not_assessed": 0 }
},
"missing_required_skills": [],
"listed_but_not_demonstrated": ["Git", "CI/CD", "Kubernetes"]
```

The same report's first piece of section order advice. The job has no employment terms, so `job.employment_terms` is `[]`.

```json
"section_advice": [
  {
    "kind": "move_bullet_up",
    "message": "Move this bullet up to the first two bullets of Senior Data Engineer at Example Mutual Insurance: \"Wrote Python data-quality checks that run before every load and block bad files from reaching reporting tables.\" It is bullet 4 of 5 there and proves 1 required requirement (\"Strong Python and SQL\"), more than one of the first two bullets does.",
    "span_ids": ["s9"],
    "requirement_ids": ["r6"]
  }
]
```

The profile read from the same resume in November 2026 (only the first of the two roles shown):

```json
"profile": {
  "roles": [
    {
      "title": "Senior Data Engineer",
      "employer": "Example Mutual Insurance",
      "client": null,
      "section": "experience",
      "start": "2022-03",
      "end": null,
      "is_current": true,
      "months": 57,
      "header_span_id": "s5",
      "bullet_span_ids": ["s6", "s7", "s8", "s9", "s10"]
    }
  ],
  "total_years": 7.5,
  "education": [
    { "degree": "B.S. Computer Science", "school": "Example State University", "year": 2019, "span_ids": ["s20"] }
  ],
  "metric_bullets": ["s6", "s7", "s8", "s13"],
  "metrics": { "s6": ["5 hours to 90 minutes"], "s7": ["14"], "s8": ["40+"], "s13": ["120"] },
  "warnings": []
}
```

One requirement in detail (evidence trimmed to one line per skill):

```json
{
  "requirement": {
    "text": "Comfortable with Git and CI/CD practices",
    "priority": "required",
    "skills": ["Git", "CI/CD"],
    "free_text_skills": []
  },
  "status": "partial",
  "skills": [
    {
      "skill": "Git",
      "strength": "listed",
      "evidence": [
        {
          "span_id": "s18",
          "text": "Cloud and tools: AWS, Git, CI/CD, Docker, Kubernetes",
          "section": "skills",
          "page": 1,
          "matched_term": "Git"
        }
      ]
    }
  ],
  "related_evidence": [],
  "years_found": null,
  "next_action": "Git and CI/CD appear only in your skills or summary. If you used them in a job or project, add a bullet that says where and what you did."
}
```

## How it works

```mermaid
flowchart LR
    L[Login: session token] --> N[Consent notice: consent=true, optional llm_consent]
    N --> A
    A[PDF or DOCX] --> V[Malware scan: ClamAV]
    V --> B[File checks: type from bytes, size, pages, zip bombs]
    B --> C[Extraction: headings, bullets and lines with section and page]
    C --> S[Structure: roles, dates, years, education, measurable results]
    D[Job description text] --> E[Parser: Claude with checks and consent, or the rules; employment terms set apart]
    C --> F[Exact matcher and skill catalog]
    S --> F
    E --> F
    C -.-> M[Optional: embedding search, then cross-encoder rerank]
    E -.-> M
    M -.-> F
    F --> G[Report: evidence per requirement, gaps, next steps, section advice]
    G --> H[(Database: owner only, with consent, expires after 24 hours)]
    G -.-> R[Optional, with llm_consent: Claude rewrites a supporting bullet]
    R -.-> K[Fact checker discards rewrites that add facts]
    K -.-> H
    H --> Q[Gap and metric questions; answers kept apart]
    H --> X[Corrections and accepted rewrites applied to a Word file]
    H --> Y[Match report: HTML and Markdown]
```

A skill counts as demonstrated when it appears in an experience, project or certification line, or in a role read from a resume that has no experience heading. It counts as listed when it appears only in the skills section, summary or header. Requirements then get one of five statuses:

| Status | Meaning |
| --- | --- |
| `direct` | Every skill the requirement names is demonstrated. For "X or Y" requirements, one is enough. For "5+ years of experience", the dated roles add up to at least that. For a degree or certification, the education or certification lines show it. |
| `partial` | Some skills are missing or appear only in the skills list, the roles that mention a skill add up to fewer years than the requirement asks for (or have no dates the app can read), or the version a requirement asks for ("Angular 12 or later") isn't shown. |
| `adjacent` | No exact evidence, but matching by meaning found a related line in experience or projects. A person has to confirm it. |
| `gap` | None of the skills appear anywhere in the resume, the dated roles add up to fewer years than asked for, or no degree at the asked level or certification line for the asked certification is listed. |
| `not_assessed` | The requirement names no skill the catalog knows ("Excellent communication skills") and nothing related was found, it asks for years and no role dates could be read, or it asks for a degree or certification the app can't judge on its own. A person has to check it. |

The skill catalog is `app/data/skills.json`. Each skill has terms that match case-insensitively, terms that match only with exact capitals (so "the rest of the team" isn't REST and "it was said in jest" isn't Jest), and very short names that count only inside a list ("Python, Go, SQL" but not "go to the office"). A term can count for two skills: "EKS" is both Kubernetes and Amazon EKS, and "Terraform" is both Terraform and infrastructure as code. In a requirement, a skill whose every mention sits inside a longer term of another skill is left out, so "Experience with GitHub Actions" asks for GitHub Actions and not also for Git, and "SQL Server" doesn't ask for SQL. Resume evidence still counts every mention.

### Roles and years

In the experience section, a line that isn't a bullet and holds a date range is a role header. These all work:

```
Senior Data Engineer, Example Mutual Insurance | Mar 2022 - Present
Example Corp - Data Analyst (2019 - 2021)
Example Corp: Data Analyst, Jun 2019 - Feb 2022
Data Analyst at Example Corp, Tampa, FL, Jun 2019 to Feb 2022
Data Analyst, Example Corp
03/2019 - 2021-12
```

The fifth one is a title line followed by a line with only the dates. The title and employer can also sit on separate lines before the dates ("Example Corp", then "Data Analyst | Jun 2019 - Feb 2022"), the employer can come on the line after a title with dates, several titles can follow one employer line, and resumes can use "Company: Example Corp" with "Role: Developer". A city and state, a state, a country or a work mode ("Remote") after the employer is dropped, so "Example Mutual, Jacksonville, FL" is Example Mutual. A city is only dropped together with the state after it, or right after a name with a company suffix ("Demo Infotech Pvt. Ltd, Hyderabad"), and "Washington" alone is read as a state, so the employer before it stays.

A name that ends with a company suffix marks an employer, never a title, whichever side of the separator it is on. The legal forms (Pvt. Ltd., Private Limited, Ltd., Limited, Inc., LLC, LLP, Corp., Corporation, GmbH) and Infotech and Softech always count. Technologies, Solutions, Consulting, Services and Systems count only in a name without a job-title word, so "Solutions Architect" and "Director of IT Systems" stay titles. Consultants often list the firm that employs them, then the client, then the title:

```
Demo Infotech Pvt. Ltd., Hyderabad, India
Client: Placeholder General Insurance (USA)
Guidewire Developer | Aug 2018 - May 2021
```

That is the title Guidewire Developer, the employer Demo Infotech Pvt. Ltd. and the client Placeholder General Insurance. A "Client:" (or "End client:", "Customer:", "Account:") line above or below the header is kept in the role's `client` field and is never its title or employer, so a resume that names only the client has no employer for that role.

Dates can be written "Mar 2022", "March 2022", "03/2022", "2022-03" or "2019", joined by a hyphen, an en dash, an em dash or "to". The bullets that follow belong to that role until the next header or section. A projects section counts as roles only when it has dated headers, and projects never add to years of experience.

A resume with no experience heading has its roles read from the lines that hold a date range, starting at the first such line and leaving out degree lines, and its degrees from the lines that name one. The profile says so in a warning, because this is less certain than a resume with headings.

A role's months include both the start and the end month, so Jun 2019 to Feb 2022 is 33 months. Overlapping roles are merged before the months are added up, and the total is rounded to one decimal. "Present" is counted up to the current month. A date the app can't read becomes a warning in the profile, never a guess.

A requirement such as "5+ years of experience" is proven when the total reaches it and missing when it doesn't. "7+ years with Java" keeps the skill rules above, but when the roles that mention Java add up to less than 7 years it is partial at most, and the next step gives the number the resume shows.

### Degrees, certifications and versions

A requirement that asks for a degree or a certification is checked against the education entries and the certification lines, never against skills used at work. A Python bullet doesn't prove "AWS Certified Solutions Architect", and a degree in the skills list doesn't count.

| Requirement | Resume | Result |
| --- | --- | --- |
| Bachelor's degree in Computer Science | B.S. Computer Science, or a higher degree in it | Proven |
| Bachelor's degree in Computer Science or a related field | B.S. Information Systems | Proven: a computing field |
| A master's degree or PhD in a quantitative field | M.S. Data Science | Proven |
| Bachelor's degree in Computer Science | B.A. History | Needs a check: the field is for the person or employer to judge |
| A master's degree or PhD | Only a bachelor's degree, or no education at all | Missing |
| Bachelor's degree or equivalent experience | No education | Needs a check |
| Certified Kubernetes Administrator (CKA) or similar certification | Any Kubernetes certification | Proven |
| AWS Certified Solutions Architect | AWS Certified Developer | Needs a check: another certification from the same vendor |
| AWS Certified Solutions Architect | No AWS certification line | Missing |

Degree levels count upward: a master's degree meets a bachelor's requirement. Fields are compared by their words ("Computer Science" in "M.S. Computer Science and Engineering"), and "related", "technical" or "quantitative" fields accept a degree from a matching family (computing, engineering, mathematics and statistics, sciences, business). A field the rules don't know is never guessed to match. Gap questions for these ask whether the person has the degree or certification and where to add it.

A requirement that names a minimum version ("Angular 12 or later", "Java 11+") is proven only when a work bullet that names the skill also gives a version at least that high. Without one it is partial, and the next step asks the person to add the version if it is true.

### Matching by meaning

Exact matching misses work described in other words. When matching by meaning is on, an embedding model (all-MiniLM-L6-v2 by default) turns each resume line and each requirement into a vector, and the 8 closest lines by cosine similarity become candidates. A cross-encoder (ms-marco-MiniLM-L6-v2) then reads the requirement and each candidate together and scores the pair from 0 to 1. Lines scoring 0.5 or more are returned as `related_evidence`, each with its section, page and score.

Related evidence never replaces exact evidence. A requirement with exact evidence keeps its status, and lines that are already exact evidence aren't repeated. A requirement that would be a gap or not assessed becomes `adjacent` when a related line comes from experience or projects. Its next step quotes that line and asks the person to confirm it really shows the requirement, and to use the job description's wording only where it is true. The named skill still counts as missing in `missing_required_skills`. A requirement that asks only for years ("5+ years of experience") is never marked adjacent, because a similar bullet doesn't add years.

If a model fails while scoring, the report falls back to exact matching and says so in its warnings.

### The Claude job-description parser

With a key and the person's consent for Claude, the job description goes to Claude (`LLM_PARSE_MODEL`, Haiku by default) with the prompt in `app/llm/prompts/jd_parse_v1.md`. The request offers one tool whose input schema is the expected output and forces Claude to call it, so the answer arrives as structured data. The app checks that answer before using any of it:

- Each requirement's text must appear in the job description once spacing is normalized. A requirement that doesn't is dropped, counted in `dropped_requirements` and mentioned in the report's warnings, so Claude can't add a requirement the posting doesn't have.
- Each skill must be named in its requirement's text. A skill that matches a catalog term becomes that catalog skill ("Apache Kafka" is Kafka). Any other skill ("Great Expectations") is kept as a free-text skill and listed in `free_text_skills`. Exact matching looks for a free-text skill in the resume as a whole phrase, ignoring case, and matching by meaning can still find related lines for it.
- Catalog skills in the text that Claude left out are added, so Claude never knows fewer catalog skills than the rules.
- Years are kept only when the requirement's text states that number of years. A title that isn't in the text is replaced by the rule parser's title.
- An employment term is dropped and an intro sentence becomes context, by the same rules as the rule parser, and the job's `employment_terms` are the rule parser's.

A timeout, an API error, output that doesn't match the schema, or an answer with no valid requirement makes the rule parser read the job description instead.

### Rewrite suggestions and the fact checker

You choose requirements (or all of them), and for each one with evidence (direct, partial or adjacent) the app picks the best supporting bullet: the first work bullet that names the requirement's skill, or for an adjacent requirement the related line that scored highest. Only work bullets are sent. Headings, the name and contact lines, role header lines, skills lists and any line holding a date range never are. Claude (`LLM_REWRITE_MODEL`, Sonnet by default, prompt `rewrite_v1.md`) gets that one requirement and that one bullet and returns up to two rewrites.

Every rewrite then goes through the fact checker in `app/services/factcheck.py`, which compares it with the bullet and lists each fact the rewrite adds. A rewrite with anything on the list is discarded and counted. The checker doesn't call a model, so the same pair always gets the same verdict. These count as added facts:

- A number the bullet doesn't have. Different ways of writing the same number match: "40+", "40 or more" and "over 40"; "5 hours" and "five hours"; "90 minutes" and "1.5 hours"; "35%" and "35 percent"; "$310K" and "$310,000"; "p95" and "95th percentile". A number with a new unit or a new bound ("40" becoming "40+") counts, and in "from 5 to 90 minutes" the 5 is read as minutes. Multiplier words such as "doubled", "twice" and "half" are numbers, so "improved" becoming "doubled" fails, and so does "a team" becoming "a team of 8".
- A year, month, quarter or other date the bullet doesn't have.
- A catalog skill the bullet doesn't name. An acronym and its spelled-out form count as the same skill ("CI/CD" and "continuous integration and delivery").
- A capitalized name the bullet doesn't have, such as an employer, client, product or tool, wherever it stands: "at Amazon", "for Acme Corp" and "with Microsoft" all fail. A name passes only when it is the same word in another case, a catalog term for a skill the bullet names, an acronym of words in the bullet ("AKS" for "Azure Kubernetes Service"), or a vendor name directly before a product the bullet names ("Amazon Redshift" for "Redshift"). Spelling an acronym out in capitalized words fails, because the checker can't tell a true expansion from an invented one. Two products the catalog files under one skill are still different names, so "GitLab" becoming "GitHub" fails.
- A certification ("certified", "licensed", "PMP") the bullet doesn't mention.
- A bigger claim than the bullet makes: leadership or ownership words ("led", "owned", "designed", "architected"), absolutes ("all", "company-wide", "end-to-end", "eliminated"), new qualities ("real-time", "scalable"), a new kind of result ("improving reliability" when the bullet states no improvement), a dropped hedge ("helped" or "contributed to" removed) and a new frequency ("daily").
- A rewrite more than twice as long as the bullet.

Reordering, trimming and a stronger verb for the same action pass. Each discarded rewrite is counted in the response's `rejected`, and each kept one is stored with its source line, requirement, prompt version and model.

Each analysis may ask Claude for at most `LLM_MAX_SUGGESTIONS` rewrite candidates in all (20 by default), which bounds cost: a request asks for two per requirement until the allowance runs out. Candidates count when Claude answers, whether or not they pass. A timeout or API error stops the request rather than waiting on every remaining requirement.

### Section order advice

The report's `section_advice` says where to move lines so the strongest evidence is read first. It is deterministic, never changes the resume, and each item has a `kind`, a plain `message` naming the line and the requirements it proves, and the `span_ids` and `requirement_ids` it is about.

- `move_bullet_up`: in each role, a bullet proves a requirement when it is demonstrated evidence for a direct or partial one. Bullets are ranked by the required requirements they prove, then the preferred ones. A bullet below the first two that proves more than one of the first two is advised up, at most one for each of the first two it would replace, so the advice never pushes out a bullet that proves as much.
- `move_project_up`: a project in a projects section that is the only work showing a skill a required requirement asks for ("No role in your experience shows TypeScript") is advised higher, in the words of the specification: "Bring this project higher in the experience section, or move the projects section above experience". A project already read before the experience section and first among the projects gets no advice.
- `skills_first`: when the skills section comes after experience and the job's required and preferred items name at least 8 distinct tools, the report says that some readers scan the skills section first. It is labeled a suggestion only.

### Corrections, gap and metric questions, and export

A correction replaces the text of one line the app read wrongly. It is your own text, so it doesn't go through the fact checker, and it is listed as a user correction, apart from rewrites. A line with an accepted rewrite can't be corrected until the rewrite is rejected, and a suggestion made before a line was corrected can't be accepted afterwards, so every accepted rewrite was checked against the exact line it replaces.

Gap questions come from the report alone, with no model call: "Have you used Kafka? If yes, where, and what did you build with it?" for a missing skill, a question about earlier dated work for a missing years requirement, and a question quoting the related line for an adjacent one.

Metric questions follow them in the same list, with `kind` "metric". An experience bullet with no measurable result (the profile's `metric_bullets` already lists the bullets that have one) gets "No number in this bullet: "...". How many, how much, how fast or how often? Add a number only if you know it." Bullets that support required requirements come first, then preferred, then job duties, then the rest, and there are at most five per analysis. A bullet with a number written as a word ("three engineers") gets none. The answer is stored like a gap answer and never put into the resume: the app never fills in a number.

The Word file is rebuilt from the lines the app read, in their original order, with corrections and accepted rewrites applied. Nothing else changes, apart from section headings, which are written in standard form ("PROFESSIONAL EXPERIENCE" becomes "Experience"), and the separator before a role's dates (" | ", a comma or a dash), which becomes a tab so the dates sit at the right margin. The file is a single column on Letter paper: the name, contact lines, Word's Heading 1 style for section headings (shown in capitals with a rule under them), bold role and degree lines, bold labels on "Label: values" lines and Word's List Bullet style, in Calibri with single spacing. It has no tables, text boxes, headers, footers or images, its language is en-US and its title "Resume", and its author and comment properties are empty. The uploaded file is never stored, so it is never modified.

### The match report

`GET /api/v1/analyses/{id}/report.html` and `/report.md` give the same report: when it was made and when it expires, a note that employers use different applicant tracking systems and criteria and that the report is not a prediction of any employer's decision, coverage per priority, each requirement with its status in words, its evidence quotes with section and page, related evidence and next step, the section order advice, the gap and metric questions with your answers, the terms noticed in the posting, the roles read and the warnings. The HTML has `lang="en"`, one h1 and headings in order, tables with a caption and `th` cells with `scope`, dark text on white, no scripts and nothing loaded from anywhere: its only style is one inline block, which its Content-Security-Policy allows by hash. Both are owner only and count against `RATE_LIMIT_EXPORTS`.

## Evaluation

`python -m evals.run` measures the app against a hand-labeled set in `evals/data/`: 12 fictional resumes, 8 fictional job descriptions and 16 resume and job pairs with 176 requirement labels, plus 100 labeled fact-check cases. Each resume is rendered into a PDF in two bullet layouts and a DOCX file, and goes through the app's own pipeline with the labels' date (2026-11-01) as today. The full results, with tables per format, confusion matrices and the error analysis, are in [evals/results/REPORT.md](evals/results/REPORT.md).

v1.0 adds three reading fixes (company suffixes and "Client:" lines in role headers, employment terms, intro sentences). On the development set, v1.0 gives the same numbers as the v0.5 column of the table below; the held-out results changed, as the next section shows. v1.0 also adds document quality to the run (see below).

v0.4 measured this set and listed the failure patterns it found. v0.5 fixed those patterns with general rules (role layouts, PDF line joining, job-description headings and boilerplate, the skill catalog, degree and certification requirements), and the PDF builder now keeps en dashes. These are the default-mode results (exact matching and the rule parser) before and after, on the development set (used to find and fix these failures, so these numbers are optimistic):

| What is measured | v0.4 | v0.5 |
| --- | --- | --- |
| Roles found, title and employer matching the label (all formats) | 78.1% (82/105) | 100.0% (105/105) |
| Total years of experience within 0.5 of the label | 72.2% (26/36) | 100.0% (36/36) |
| Labeled requirement lines the parser found | 100.0% (121/121) | 100.0% (121/121) |
| Extracted lines that are labeled requirements | 88.3% (121/137) | 100.0% (121/121) |
| Priority right on the lines found | 90.9% (110/121) | 100.0% (121/121) |
| Requirement status matches the label (all formats) | 68.6% (362/528) | 90.3% (477/528) |
| Marked proven where the label says gap or needs a check | 0.0% (0/174) | 0.0% (0/174) |
| Marked proven where the label says anything else | 3.9% (9/234) | 2.6% (6/234) |
| Gap recall | 69.4% (102/147) | 95.9% (141/147) |
| A labeled evidence line among the first three the report cites | 57.6% (204/354) | 74.6% (264/354) |
| Fact checker accuracy, held-out set | 97.5% (39/40) | 97.5% (39/40) |
| Rewrites that add a fact but pass the fact checker, held-out set | 0.0% (0/20) | 0.0% (0/20) |

### Held-out results

The numbers above come from data the fixes were written against. The fairer test is `evals/data/holdout/`: 6 more fictional resumes, 5 job descriptions and 8 pairs with 110 requirement labels, written by someone who never saw the app's code, its results or the development labels. v0.4 and v0.5 were run on it once each, after v0.5 was finished, with the same corrected PDF builder. Those two runs are the blind results.

This set is no longer fully unseen. During a manual demo after v1.0, one held-out example showed three reading errors: an employer with "Pvt. Ltd." read as the title, a "Client:" line read as the employer, and the posting's "Only W2" and "We are looking for a hands-on..." lines read as requirements. v1.0 fixes them with general rules, tested on new examples and not on that one, but they were found by looking at a held-out example, so the third column below is not a blind result. The set's own README says that once a change is made because of it, a new held-out set should be written; that hasn't been done yet.

| What is measured, held-out set | v0.4 (blind) | v0.5 (blind) | v1.0 (after fixes informed by one held-out example) |
| --- | --- | --- | --- |
| Roles found, title and employer matching the label (all formats) | 44.4% (24/54) | 77.8% (42/54) | 83.3% (45/54) |
| Labeled requirement lines the parser found | 97.8% (88/90) | 97.8% (88/90) | 97.8% (88/90) |
| Extracted lines that are labeled requirements | 83.0% (88/106) | 93.6% (88/94) | 95.7% (88/92) |
| Requirement status matches the label (all formats) | 50.9% (168/330) | 64.5% (213/330) | 64.5% (213/330) |
| Marked proven where the label says gap or needs a check | 4.0% (6/150) | 2.0% (3/150) | 2.0% (3/150) |
| A labeled evidence line among the first three the report cites | 36.7% (66/180) | 53.3% (96/180) | 53.3% (96/180) |

The v0.4 column was run again for this release, the v0.4 app with the v0.5 evaluation code, and gave the same numbers as the original run; both blind runs are kept in `evals/baselines/holdout.json`. The fixes carried over to new data, but the held-out numbers sit well below the development ones, which is the honest picture of how the app does on resumes and postings it hasn't seen. The v1.0 fixes moved roles and requirement extraction, not statuses or evidence. The remaining overclaim is one requirement counted in each format: "Experience with Tabular Editor and DAX Studio" was marked proven by a bullet about DAX measures, because the catalog treats a tool and the language it works with as one skill. v0.4's two overclaims on this set had the same cause ("Guidewire Jutro" proven by other Guidewire work, a "Platform Developer II" certification proven by "Platform Developer I"); v0.5's certification matching fixed the second. The full report is in [evals/results/holdout/REPORT.md](evals/results/holdout/REPORT.md). The held-out set has no fact-check cases of its own; the fact checker's held-out result is the 40-case set above.

### Document quality

Every development resume, in all three formats, is exported with the app's own Word export and read back with the app's own extractor and pipeline. All 36 files keep the section of every line, their roles (title, employer, start and end) and their total years, and all 48 pair and format combinations keep every requirement's status (100.0%, 36/36 and 48/48). All 36 files pass the structural check: no tables, text boxes, images, headers or footers, one column, section headings in Word's Heading 1 style, bullets in its List Bullet style and the language set to en-US. Three of the files come from the resume with no section headings, so they have none to style. The held-out set gives the same result (18/18 and 24/24). This checks the export against the app's own reader. It doesn't show how any employer's system reads the file.

### Evidence rated by a person

The specification asks for a human rating of whether each matched line supports its requirement. That rating has not been done yet. `python -m evals.rating_sheet` writes [evals/results/evidence_rating_sheet.csv](evals/results/evidence_rating_sheet.csv), one row per pair, requirement and cited evidence line (340 rows for the development set, from the `pdf_inline` reading), with an empty `rating` column for a person to fill with supports, partly or does not. `python -m evals.rating_summary evals/results/evidence_rating_sheet.csv` then gives the human-rated share, overall, by status and by kind of evidence. Until someone fills it in, evidence recall against the labels is the only measure of evidence quality.

### Hallucination rate of generated suggestions

This needs your own Anthropic key and hasn't been run. With a key in `.env`, `python -m evals.run --llm` asks Claude for rewrites for every pair, counts the candidates the fact checker rejects for adding a number, date, name, tool, certification or claim (the report's "hallucination rate caught by the fact checker"), and saves every candidate with the checker's reasons to `evals/results/llm_candidates.json`, each with an empty `manual_review` field. The checker can miss an added fact, so the rate is complete only after a person has read the kept candidates and marked each one faithful or adds_fact.

Every rate shows its counts. "All formats" pools the same 12 resumes read in three formats, so it isn't three times the evidence. The builder fix alone (the v0.4 app with en dashes in its PDFs) moves status accuracy from 362 to 366 of 528 and the years within 0.5 from 26 to 28 of 36; the report has that run as a third column.

What the development run shows:

- The rules now read every labeled role, date and degree in this set and every labeled requirement line with its priority. That is the set the fixes were written against, so it says little about new resumes and postings. The held-out table above is the fair measure.
- The app still doesn't overclaim: no requirement labeled gap or needs a check is called proven. Six of the 282 proven results (two requirements in each format) disagree with a label of partial or adjacent: JUnit counted for "Jest or a similar framework", and a bullet that integrated a payments provider counted for "Experience in payments or financial services".
- Most remaining errors need matching by meaning, which wasn't run: GitLab CI for GitHub Actions, Java for C#, "Production experience with Kubernetes" from an ECS bullet. In exact mode the app never returns adjacent, so the 9 adjacent labels always count as wrong here.
- A few need wording the catalog doesn't hold, such as "statistics and model evaluation" shown by a bullet about cross-validation, or "relational databases such as PostgreSQL or Oracle" shown by a SQLite project.
- Years requirements cite no lines in the report, so they can never count in evidence recall. Without them, a labeled line is among the first three cited for 84.6% (264/312).
- The fact checker passed no rewrite that adds a fact in either set. It rejected one faithful rewrite in each: "K8s" written as "Kubernetes", and "ran" changed to "led".

To run it:

```bash
python -m evals.run              # default mode: a few seconds, no network
python -m evals.run --check      # and exit 1 if a metric is past evals/thresholds.json (CI runs this)
python -m evals.run --formats docx
python -m evals.run --data-dir path/to/set   # another labeled set with the same layout
python -m evals.run --semantic   # also matching by meaning: needs the ml extra and the model download
python -m evals.run --llm        # also the Claude parser and rewrites: needs ANTHROPIC_API_KEY
python -m evals.rating_sheet     # the evidence sheet for a person to rate
python -m evals.rating_summary evals/results/evidence_rating_sheet.csv   # once it is rated
```

`--data-dir` takes any folder with `resumes/`, `jobs/` and `labels/` laid out like `evals/data/`, and writes its results to `evals/results/<folder name>/` unless `--out` is given, so it never overwrites the development results. The fact-check labels are optional there. Without sentence-transformers or a key, `--semantic` and `--llm` are skipped with a message that says how to run them. With them, the report shows exact and semantic results side by side with a sweep of reranker thresholds, and the Claude rewrites go to `evals/results/llm_candidates.json` with the fact checker's verdict and reasons for each. [evals/README.md](evals/README.md) has the details, and [evals/data/README.md](evals/data/README.md) the labeling conventions.

Read the numbers with these limits in mind:

- The development numbers are optimistic. v0.5 was written by reading this set's failures, even though every fix is a general rule and none names a string, person or company from it.
- The set is small. One item moves a per-format status rate by about half a point and a per-job rate by several.
- The labels were written by the project team, alongside the fictional resumes and job descriptions, which are cleaner and more regular than real ones.
- `factcheck.json` was used while the fact checker was built, so the report gives it separately as a development set (98.3%, 59/60), labeled optimistic. The held-out 40 cases are the primary result for the fact checker.
- Matching by meaning and Claude weren't run for these numbers. They don't run in CI, and the model downloads and the Anthropic API weren't available while building v0.4, v0.5 or v1.0, so the threshold of 0.5 is still untuned and the hallucination rate of generated suggestions is unmeasured.
- The held-out set is no longer fully unseen since the v1.0 fixes (see above), and no person has rated the evidence yet.
- Every PDF comes from one builder (`tests/builders.py`). Since v0.5 it embeds its font, so an en dash reaches the app as written. Real Word or Google Docs exports, two-column layouts and text boxes aren't covered.

## Configuration

Settings come from environment variables or a `.env` file. See `.env.example`, which lists every one of them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `local` | `local` or `production`. Production refuses to start with SQLite, without `sslmode=require` (or `verify-ca`, `verify-full`) in a Postgres URL, with a database URL that has no password, with `AUTH_MODE=disabled`, with `CORS_ORIGINS=*`, with `LLM_ENABLED=on` and no key, or with `SCANNER=off` unless `ALLOW_UNSCANNED_UPLOADS=true`. It also sends `Strict-Transport-Security`. |
| `LOG_LEVEL` | `INFO` | Log level for the JSON logs. |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLite for local work and tests. Postgres in production: `postgresql+psycopg://user:password@host:5432/dbname?sslmode=require`. `postgres://` and `postgresql://` URLs get the psycopg driver added. |
| `DB_AUTO_MIGRATE` | empty | Run `alembic upgrade head` at startup. Empty means yes locally and no in production, where the migrations run once as a separate step and the app refuses to start while any are pending. |
| `AUTH_MODE` | `required` | `required`: every analysis endpoint needs a login. `disabled`: one local account for everyone, for a single-user demo on your own machine. Production refuses `disabled`. |
| `SESSION_TTL_HOURS` | `12` | How long a login session lasts. Logging out ends it sooner. |
| `MAX_UPLOAD_MB` | `5` | Largest resume file accepted. |
| `MAX_PDF_PAGES` | `10` | Longest PDF accepted. |
| `MAX_JD_CHARS` | `20000` | Longest job description accepted. |
| `MAX_DOCX_UNCOMPRESSED_MB` | `50` | Largest unpacked size of a Word file, which stops zip bombs. |
| `RETENTION_HOURS` | `24` | Stored analyses are deleted after this. |
| `CORS_ORIGINS` | `http://localhost:8501` | Browser origins allowed to call the API, comma-separated. Only these get CORS headers. |
| `TRUSTED_PROXIES` | empty | Addresses and CIDR ranges of proxies whose `X-Forwarded-For` gives the client address, comma-separated. Empty trusts none, and the connecting address is used. |
| `SCANNER` | `off` | `off`, or `clamav` to scan every upload with clamd before it is read. |
| `CLAMAV_HOST` | `localhost` | Where clamd listens. |
| `CLAMAV_PORT` | `3310` | clamd's TCP port. |
| `CLAMAV_TIMEOUT_SECONDS` | `30` | Longest wait for clamd to answer. |
| `ALLOW_UNSCANNED_UPLOADS` | `false` | Lets production run with `SCANNER=off`. The app then logs a warning at every start. |
| `RATE_LIMITS_ENABLED` | `true` | Turns the rate limits off when `false` (production logs a warning). |
| `RATE_LIMIT_AUTH` | `5/minute` | Logins and registrations per email tried. |
| `RATE_LIMIT_ANALYSES` | `30/hour` | New analyses and text extractions per account. |
| `RATE_LIMIT_SUGGESTIONS` | `30/hour` | Requests for rewrite suggestions per account. |
| `RATE_LIMIT_EXPORTS` | `60/hour` | Word file and match report downloads per account. |
| `RATE_LIMIT_IP_MULTIPLIER` | `5` | Each client address gets this many times each limit, so people behind one address don't use up each other's allowance. |
| `SEMANTIC_MATCHING` | `auto` | `off`, `on` or `auto`. `auto` turns matching by meaning on only when sentence-transformers is installed. `on` stops the app at startup if the models can't be loaded. |
| `SEMANTIC_TOP_K` | `8` | Resume lines the embedding search passes to the reranker for each requirement. |
| `SEMANTIC_THRESHOLD` | `0.5` | Reranker score, from 0 to 1, that a line needs to count as related. |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model for the first search. |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L6-v2` | Cross-encoder that scores each candidate line. |
| `LLM_ENABLED` | `auto` | `off`, `on` or `auto`. `auto` turns Claude on only when `ANTHROPIC_API_KEY` is set. `on` stops the app at startup without a key. |
| `ANTHROPIC_API_KEY` | empty | Key for the Anthropic API. Set it in your local `.env` (see [Turning on Claude](#turning-on-claude)) or as a secret of the deployment, never in the repo. |
| `LLM_PARSE_MODEL` | `claude-haiku-5-5` | Model that reads job descriptions. |
| `LLM_REWRITE_MODEL` | `claude-sonnet-5-5` | Model that writes rewrite suggestions. |
| `LLM_TIMEOUT_SECONDS` | `30` | Longest wait for one attempt. Rate limits, server errors, timeouts and dropped connections are retried up to twice, with backoff. |
| `LLM_MAX_SUGGESTIONS` | `20` | Rewrite candidates one analysis may ask Claude for, in all. |

Rate limits are written as a count and a unit: `10/minute`, `30/hour`, `5/second` or `100/day`.

The consent notice has no settings of its own. `GET /api/v1/consent` builds it from `RETENTION_HOURS`, `SCANNER` and whether Claude is on, so it always describes what this server does. Its wording is versioned in the code (`consent_v1` in `app/services/consent.py`), and that version is stored with every analysis.

A few settings belong to the containers rather than the app:

| Variable | Where | Purpose |
| --- | --- | --- |
| `RUN_MIGRATIONS` | API image | `true` runs `alembic upgrade head` in the entrypoint before the command. docker compose sets it, and the Azure migration job uses it. |
| `INSTALL_ML` | API image build | `true` builds the image with sentence-transformers and CPU-only PyTorch. docker compose passes it through. |
| `API_URL` | Streamlit screen | Where the screen finds the API. Default `http://localhost:8000`, and `http://api:8000` in its image. |
| `POSTGRES_PASSWORD` | docker compose | The password of the local Postgres container. It has a default for local use only. |

## Security and privacy

### What is stored, and for how long

- The account: its email (lowercased), an argon2id hash of the password (RFC 9106's low-memory parameters) and when it was made. It is kept until the account is deleted.
- Login sessions: the SHA-256 hash of each token, never the token itself, with its start and end time. A session ends after `SESSION_TTL_HOURS` (12 by default), at logout, or when the account is deleted, and ended sessions are removed.
- Each analysis: the report, a SHA-256 hash of the file, the lines the app read from the resume (needed for corrections and export), when you gave consent and the version of the notice you agreed to, whether Claude may see your text, your corrections, the rewrite suggestions with their source lines and your decisions, your answers to gap and metric questions, and for each suggestion request the counts and token usage (never text). All of it is deleted after `RETENTION_HOURS` (24 by default), or sooner when you delete the analysis or the account.
- Uploaded files are parsed in memory and never written to disk or stored.
- Rate-limit counters live in the API's memory, keyed by account id, client address and a SHA-256 hash of the email tried, and are gone when it restarts.
- Logs record request ids, user ids, the route each request matched (its template, such as `/api/v1/analyses/{analysis_id}`, never the URL as sent), status codes, timings, the counts above, and for each call to Claude the model, prompt version, token counts and latency. They never contain emails, passwords, tokens, resume text, job-description text, prompts or the key. An error's traceback is logged without its message, because messages from libraries can quote input. The Anthropic SDK and the HTTP libraries are held at the warning level, because at debug level they log request bodies.

### Consent

Before an upload, the screen shows the notice from `GET /api/v1/consent`: what is stored, that it is deleted after `RETENTION_HOURS` or when you ask, that only your account can see it, whether uploads are scanned, and, only when Claude is on, which text goes to Anthropic. One box is required and sends `consent=true`; without it the API answers 422 `consent_required` before it reads, scans or counts anything. A second box, shown only when Claude is on, sends `llm_consent=true`. Without it the rules read the job description even when Claude is on, and `POST .../suggestions` answers 409 `llm_consent_required`. The consent time, the notice's version and the Claude choice are stored with the analysis and returned in its `consent` field. Consent for Claude sent to a server where Claude is off is stored as false, because no notice about Anthropic was shown.

The app doesn't infer or score protected characteristics. Employment terms that touch on citizenship or visa status are listed as terms noticed in the posting and never used to score anyone.

### Who can see it

Only the account that made an analysis can see it, change it or delete it. Any other account gets 404 for its id, the same answer as for an id that doesn't exist. There is no admin screen that shows analyses, and `python -m app.admin` can only reset a password or delete an account. Whoever runs the server and can open its database can read what is stored there, as with any hosted service. With `AUTH_MODE=disabled` everything belongs to one local account, so anyone who can reach the API sees everything, which is why production refuses that setting.

### Deleting

`DELETE /api/v1/analyses/{id}`, or the button on the screen, deletes the analysis and every row stored with it at once. `DELETE /api/v1/auth/me`, or "Delete my account and data" on the screen, deletes the account, its sessions and every analysis it owns, with everything stored with them, in one transaction. The operator can do the same with `python -m app.admin delete-user <email>`. The managed Postgres in the Azure template keeps backups for 7 days, so deleted rows stay in those backups until they age out.

### What goes to Anthropic

Nothing, unless a key is configured and you tick the Claude box for that analysis (`llm_consent=true`). Then the job-description text is sent to Anthropic for parsing, and when you ask for suggestions, each chosen requirement's text and the one resume bullet picked for it are sent. The whole resume, the uploaded file, your name and contact lines, your email, your corrections and your gap answers are never sent, though a bullet that names a person or an employer is sent as written. Anthropic's API terms cover what is sent. Matching by meaning runs both models inside the API process and sends nothing anywhere. Its only outside request is the one-time model download from Hugging Face.

### Malware scanning

With `SCANNER=clamav`, every upload is streamed to ClamAV's clamd over TCP (its INSTREAM command) before the app opens it. A flagged file is refused with 422 and nothing is stored, and the log records the signature name and the account id, never the file. If clamd can't be reached, times out or gives any other answer, the upload is refused with 503 and `Retry-After`: the scanner fails closed, and `/readyz` reports the API as not ready. Production refuses to start without scanning unless `ALLOW_UNSCANNED_UPLOADS=true` is set, and then logs a warning at every start. docker compose and the Azure template both run ClamAV. The file type is then decided from the file's bytes, not its name, and Word archives are checked for unpacked size before opening.

### Rate limits

Each limit is a token bucket. Logins and registrations are limited per email tried (5 a minute by default), new analyses and text extractions (30 an hour), suggestion requests (30 an hour) and Word exports and match reports together (60 an hour) per account, and each client address gets five times each limit. A request over a limit gets 429 with `Retry-After` in seconds. The buckets live in the memory of each API process: they reset when it restarts, and with several replicas each counts on its own, so the real limit would be the limit times the number of replicas. Run one replica (the Azure template does) until the limits move to a shared store. The client address comes from `X-Forwarded-For` only through the proxies listed in `TRUSTED_PROXIES`.

### Encryption

In transit: on Azure, the Container Apps ingress serves both apps over HTTPS only (TLS 1.2 or 1.3, with certificates Azure manages) and redirects plain HTTP, and the API adds `Strict-Transport-Security` in production. The connection to the database is encrypted too: the Postgres server requires TLS, and the app refuses to start in production without `sslmode=require`. With docker compose on your own machine, the ports are plain HTTP on localhost and the containers talk over Docker's private network without TLS, which is fine for local use only.

At rest: Azure's Postgres Flexible Server encrypts its storage and backups with keys the service manages. The app adds no encryption of its own on top.

### Hardening

Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a Content-Security-Policy that lets JSON responses load nothing. The docs page at `/docs` gets its own policy, which allows its one inline script by hash, and the match report's HTML gets one that allows only its own inline style, also by hash. API responses carry `Cache-Control: no-store`, because reports quote the resume. CORS headers go only to the origins in `CORS_ORIGINS`. Both images run as a non-root user.

### Not done yet

- Email verification: no email is sent, so an account's email is never confirmed to belong to the person. It is only a login name.
- Password reset by email: there is none. The operator resets a password with `python -m app.admin reset-password <email>`.
- Rate limits shared across replicas.
- Single sign-on, and second factors for login.
- Private networking for the database, and checking the database server's certificate (`sslmode=verify-full`).

## Accessibility

What was checked, and how:

- The screen (`ui/app.py`) was reviewed line by line. Every input has a visible label (the email, password, file, job description, answer and correction fields and both consent boxes), no label is hidden, statuses are written in words ("Status: Proven", "Status: Missing"), warnings start with "Warning:", headings go in order (the page title, then "Check your resume against a job" and "Results", then Coverage, Required, Preferred and the rest), and nothing is shown by color alone. An error is written next to what caused it: a missing consent box, file or job description under that input, an API error about the file under the file input, a failed suggestion under its requirement card, a failed answer under its answer box and a failed correction inside the corrections form. `tests/unit/test_ui.py` drives the consent form and checks those errors.
- The HTML match report declares `lang="en"`, has one h1 and headings that never skip a level, gives each table a caption and `th` cells with `scope`, writes every status in words, uses dark text on white (17.4:1) and borders at 7:1, and has no scripts and nothing loaded from anywhere. `tests/unit/test_match_report.py` checks each of these with an HTML parser.
- The Word export sets its language to en-US and its title to "Resume", uses Word's Heading 1 style for section headings and its List Bullet style for bullets, and is one column with no tables or text boxes. `tests/unit/test_export.py` and the document quality part of the evaluation check it.

What wasn't checked:

- No person has used the screen, the report or the Word file with a screen reader (NVDA, JAWS, VoiceOver) or with the keyboard alone, and no automated audit (axe, Lighthouse, Word's Accessibility Checker) was run.
- Streamlit's own widgets and page are outside this project's control: the file uploader, tabs, expanders, tables, download buttons and the page's landmarks expose whatever names and roles Streamlit gives them, in Streamlit's default theme, whose contrast wasn't measured.

## Deployment

[docs/deploy-azure.md](docs/deploy-azure.md) walks a first-time Azure user through deploying with the template in `infra/azure/main.bicep`: a resource group, Postgres Flexible Server with TLS required, the API with ClamAV next to it, the screen, a job that runs the migrations once, the Anthropic key as a secret, the logs, the cost and tearing it all down.

The images come from GitHub. Pushing a tag such as `v1.0.0` runs `.github/workflows/release.yml`, which runs CI and then pushes `ghcr.io/<owner>/resume-evidence-matcher-api` (also with a `-ml` tag that has matching by meaning) and `ghcr.io/<owner>/resume-evidence-matcher-ui`, signing in with the workflow's own `GITHUB_TOKEN`. `.github/workflows/deploy-azure.yml`, started by hand with a tag, runs the migrations with the new image and then moves both apps to it. It signs in to Azure with OpenID Connect, so no Azure password is stored in GitHub; the guide shows the one-time setup.

Elsewhere, any host that runs containers works the same way: run the API image once with `RUN_MIGRATIONS=true` (or run `alembic upgrade head` with the same `DATABASE_URL`), then run it with `APP_ENV=production`, a Postgres `DATABASE_URL` with `sslmode=require`, `SCANNER=clamav` and a reachable clamd, behind HTTPS. Keep it to one replica while the rate limits are in memory.

## Development

```bash
pytest                      # tests, with warnings treated as errors
pytest --cov=app            # with coverage
ruff check . && ruff format --check .
mypy app evals              # strict mode
python -m evals.run --check  # the evaluation, see evals/README.md
python -m evals.run --data-dir evals/data/holdout   # the held-out set (no longer fully unseen)
python scripts/make_samples.py   # rebuild samples/generated from samples/resumes
```

The tests never load a real model and never call the Anthropic API. `tests/fakes.py` has a deterministic encoder (hashed word stems with a small synonym table) and reranker (the share of the requirement's words a line covers), and a scriptable Claude client that replays set answers and records every call. The test settings set `SEMANTIC_MATCHING=off` and `LLM_ENABLED=off`, and a fixture removes `ANTHROPIC_API_KEY` from the environment for every test, so a key on your machine is never used. The Anthropic client is tested against the real SDK with httpx2's mock transport, which checks the request it builds and the responses it parses without a network. The Streamlit screen tests run only when Streamlit is installed: they start the API on a local port and drive login, registration, logout, account deletion and the consent form through Streamlit's test runner. The tests also hash passwords with the cheapest argon2 parameters to stay fast, and one test checks the real ones. ClamAV is replaced by `tests/fake_clamd.py`, a small server on a local port that speaks clamd's protocol and flags the EICAR test string, which it puts together at runtime so no file in the repository holds it.

The tests use a fresh SQLite file each. To run the database tests against Postgres as CI does, point `TEST_DATABASE_URL` at an empty database whose name contains "test" (every table in it is dropped before each test):

```bash
TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/matcher_test pytest tests/integration
```

The fact checker's unit tests don't use the labeled cases in `evals/data/labels/`. `factcheck.json` was used while the checker was built, so the evaluation reports it separately as a development set, and `factcheck_holdout.json` is the held-out result. The evaluation's own tests in `tests/evals/` check its matching and metric functions on small hand-made inputs, run it on two pairs with the fake models and the fake Claude client, and run `--data-dir` on a tiny labeled set written to a temporary folder. The full evaluation runs in CI as `python -m evals.run --check`. When a change moves a number on purpose, rerun it and commit `evals/results/` and `evals/thresholds.json` with the change. Ruff and mypy skip `evals/data/`, which holds labeled data and never code.

Dependencies are pinned with hashes in `requirements.lock` (runtime) and `requirements-dev.lock` (dev). After changing `pyproject.toml`, regenerate them:

```bash
uv pip compile pyproject.toml --universal --python-version 3.11 --generate-hashes -o requirements.lock
uv pip compile pyproject.toml --extra dev --universal --python-version 3.11 --generate-hashes -o requirements-dev.lock
```

The ml and ui extras are left out of the lock files. PyTorch has to come from a platform-specific index (the CPU-only one in the Docker image), which a universal lock can't express.

```
app/
  api/          routes, account routes, edit routes (suggestions, corrections, gap
                answers, export), request and response schemas, security headers,
                error handling
  llm/          the LLM client interface, the Anthropic client and prompts/, the
                versioned prompt files
  migrations/   Alembic environment and versions/, the database migrations
  services/     extraction, job-description parsing (rules and Claude), skill catalog,
                structure (roles, years, education, measurable results), matching,
                degree and certification checks, version checks, matching by meaning,
                section order advice, rewrites, fact checker, gap and metric questions,
                Word export, the match report, the consent notice, passwords and
                tokens, rate limits, client addresses, malware scanning
  storage/      tables, repositories for analyses and accounts, running migrations
  data/         skills.json
  admin.py      python -m app.admin: reset a password or delete an account
  models.py     data contracts shared by the pipeline and the API
ui/             Streamlit screen and its Dockerfile
tests/
  unit/  integration/
  evals/        tests of the evaluation runner
  builders.py   builds realistic PDF and DOCX resumes for tests and samples
  fakes.py      deterministic stand-ins for the embedding model, reranker and Claude
  fake_clamd.py a stand-in for ClamAV on a local port
  support.py    test settings, accounts and the Postgres switch
samples/        fictional resumes and job descriptions
scripts/        sample generation
evals/          the evaluation: runner, thresholds, document quality, the evidence rating
                sheet and its summary, data/ (the labeled sets), baselines/ (earlier
                runs for before and after tables) and results/
infra/azure/    Bicep template and an example parameters file
docs/           the Azure deployment guide and the demo video script
alembic.ini     settings for the alembic command line
docker-compose.yml     the API, the screen, Postgres and ClamAV together
docker-entrypoint.sh   the API image's entrypoint (RUN_MIGRATIONS)
```

The database tables are created and changed only by the Alembic migrations in `app/migrations/versions/` (0001 the schema, 0002 the consent columns). After changing a table in `app/storage/db.py`, write a new revision (`alembic revision --autogenerate -m "what changed"` against a database at the newest revision, then read and fix what it wrote) and run the tests: `tests/integration/test_migrations.py` fails when the migrated schema and the tables in `db.py` differ. The app runs pending migrations at startup when `DB_AUTO_MIGRATE` allows it (by default only outside production), and otherwise refuses to start until they have run. `python -m app.storage.migrations` prints where a database stands.

Before 1.0 the tables were made with `create_all`, which kept no migration history. The first migration recognizes a SQLite file from v0.5 or earlier and upgrades it in place: it sets the old tables aside, creates the new ones, copies every row over and drops the old tables. Those analyses had no owner, so they go to the local account that `AUTH_MODE=disabled` uses, which is how v0.5 worked (one person, no login). Nobody can log in as that account, and the analyses still expire when they always would have. v0.5 shipped no Postgres driver, so a Postgres database with v0.5 tables is refused with a message instead.

## Specification coverage

Every line of the project's specification (Project 03 in the course kit), where it is built, and its status: done, needs your API key (the code and its tests are here, but it has never run against Claude), or needs a person (it can't be finished by code).

| Specification | Where | Status | Notes |
| --- | --- | --- | --- |
| Pipeline 1, ingestion: upload PDF/DOCX | `POST /api/v1/analyses` in `app/api/routes.py`, `app/services/extraction.py` | done | |
| Pipeline 1: validate file type and size | `app/services/extraction.py`, `MAX_UPLOAD_MB`, `MAX_PDF_PAGES`, `MAX_DOCX_UNCOMPRESSED_MB` | done | The type comes from the file's bytes, not its name. |
| Pipeline 1: scan for malware | `app/services/scanning.py` (ClamAV) | done | On in docker compose and the Azure template, off by default outside Docker (`SCANNER=off`), which the consent notice then says. |
| Pipeline 1: store securely | `app/storage/`, ownership checks in `app/api/` | done | The file itself is never stored; the lines and report are owner only and expire. |
| Pipeline 2, extraction: extract text and layout | `app/services/extraction.py` | done | Layout means headings, bullets, lines and pages. Two-column PDFs are read in the PDF's own order. |
| Pipeline 2: preserve section headings, dates, bullet boundaries and page references | `app/services/extraction.py`, `app/models.py` (`Span`) | done | |
| Pipeline 3, normalisation: roles, employers, dates | `app/services/structure.py` | done | With clients for consultants since v1.0. |
| Pipeline 3: education | `app/services/structure.py` | done | |
| Pipeline 3: skills | `app/services/skills.py`, `app/data/skills.json` | done | 328 catalog skills, plus free-text skills from the Claude parser. |
| Pipeline 3: projects | `app/services/structure.py`, `app/services/advice.py` | done | A projects section counts as roles only when it has dated headers. |
| Pipeline 3: certifications | `app/services/credentials.py` | done | |
| Pipeline 3: measurable outcomes | `find_metrics` in `app/services/structure.py` | done | Numbers written as words aren't read. |
| Pipeline 4, job analysis: responsibilities | `app/services/jd_parser.py` (context) | done | |
| Pipeline 4: required and preferred skills | `app/services/jd_parser.py`, `app/services/claude_jd_parser.py` | done | The Claude parser needs your API key; the rules are the default. |
| Pipeline 4: seniority | `seniority_for` in `app/services/jd_parser.py` | done | |
| Pipeline 4: domain terms | domain skills in `app/data/skills.json` | done | |
| Pipeline 4: evidence expectations | years, degree, certification and version asks in `app/services/matcher.py`, `credentials.py`, `versions.py` | done | |
| Pipeline 5, matching: exact skill matching | `app/services/matcher.py` | done | |
| Pipeline 5: semantic retrieval | `app/services/semantic.py` | done | Needs the ml extra and a model download from Hugging Face, which weren't available here, so it was tested with fake models only. |
| Pipeline 5: distinguish direct, adjacent and missing evidence | `MatchStatus` in `app/models.py`, `app/services/matcher.py` | done | Adjacent needs matching by meaning. |
| Pipeline 6, recommendations: truthful bullet rewrites | `app/services/rewrite.py`, `app/services/factcheck.py` | needs your API key | The fact checker is done and measured on 100 labeled cases; Claude has never been called. |
| Pipeline 6: section priorities | `app/services/advice.py` | done | |
| Pipeline 6: missing evidence questions | `app/services/questions.py` | done | Gap and metric questions. |
| Pipeline 7, export: a clean, ATS-readable document | `app/services/export.py`, `evals/document_quality.py` | done | Checked against the app's own reader and for structure, not against any employer's system. |
| Pipeline 7: a transparent match report | `app/services/match_report.py`, `report.html` and `report.md` | done | |
| Architecture: hybrid retrieval | `app/services/matcher.py` with `app/services/semantic.py` | done | The semantic half has the same limit as semantic retrieval above. |
| Architecture: two-stage ranking (bi-encoder then cross-encoder) | `app/services/semantic.py` | needs a person | Built and tested with fake models. The threshold of 0.5 is untuned: someone has to run `python -m evals.run --semantic` with the real models and choose it. |
| Architecture: evidence graph (every recommendation links to a source span or is marked a gap) | `Evidence`, `RelatedEvidence`, `SectionAdvice` and question `span_id`s in `app/models.py` and `app/services/questions.py` | done | |
| Architecture: requirement weighting (mandatory, preferred, contextual) | `Priority` in `app/models.py` | done | |
| Architecture: explainable scoring (category coverage and evidence, no single ATS score) | `coverage` in the report, `app/services/matcher.py` | done | |
| Architecture: truth-preserving rewrite (ask the user to confirm any missing metric or responsibility) | metric and gap questions in `app/services/questions.py`, adjacent next steps, `app/services/factcheck.py` | done | The questions are done; the rewrites they protect need your API key. |
| Evaluation: extraction accuracy (parsed entities and dates against labeled resumes) | `evals/resume_structure.py` | done | |
| Evaluation: requirement classification precision and recall | `evals/requirements.py` | done | For the rules; for Claude it needs your API key (`--llm`). |
| Evaluation: evidence mapping quality (human rating of each matched span) | `evals/rating_sheet.py`, `evals/rating_summary.py` | needs a person | The sheet is written (340 rows); nobody has rated it. |
| Evaluation: hallucination rate (unsupported skills, claims, dates or metrics in generated suggestions) | `evals/llm_mode.py` (`--llm`) | needs your API key | And a person to review the kept candidates in `llm_candidates.json`. |
| Evaluation: document quality (parsing, section order, readability, output integrity across PDF/DOCX) | `evals/document_quality.py` | done | Readability is checked as structure (one column, real headings and lists); nobody has read the files for reading ease. |
| Privacy: encryption in transit and at rest | `infra/azure/main.bicep`, `sslmode=require` checks in `app/config.py` | needs a person | Built into the template and the production checks; the project hasn't deployed it, and local docker compose is plain HTTP. |
| Privacy: short retention | `RETENTION_HOURS` | done | |
| Privacy: deletion controls | `DELETE /api/v1/analyses/{id}`, `DELETE /api/v1/auth/me` | done | |
| Privacy: clear consent | `app/services/consent.py`, `consent` and `llm_consent` | done | |
| Privacy: do not infer or score protected characteristics | `app/services/jd_parser.py` (employment terms) | done | Nothing infers them; citizenship and visa terms are listed, never scored. |
| Privacy: avoid ranking candidates | the whole app | done | One person's own resume against one job; no lists of candidates. |
| Privacy: do not claim to predict ATS pass rates or guarantee interviews, and explain that employers use different systems and criteria | the screen, the match report, this README | done | |
| Privacy: keep the original resume unchanged | `app/services/export.py` | done | The file is never stored or changed. |
| Privacy: show proposed edits side by side | `ui/app.py` | done | The suggestions themselves need your API key. |
| Privacy: require user confirmation before export | accept and reject in `app/api/edits.py` | done | Only accepted rewrites reach the export. |
| Privacy: allow the user to correct extraction errors | `PATCH .../spans/{span_id}` | done | |
| Privacy: inspect the source text behind each recommendation | evidence quotes with section and page, `GET .../spans` | done | |
| Milestone: MVP (upload, extraction, exact keyword coverage, basic report) | see above | done | |
| Milestone: semantic matching (embeddings, reranking, requirement categories, evidence mapping) | `app/services/semantic.py` | done | Real models not run here; the threshold needs a person (above). |
| Milestone: truth-preserving generation (editable suggestions, gap questions, factuality checks, export) | `app/services/rewrite.py`, `factcheck.py`, `questions.py`, `export.py` | needs your API key | Everything but the Claude calls is done and tested. |
| Milestone: production hardening (privacy controls, deletion, secure file handling, evaluation dataset, accessibility) | see [Security and privacy](#security-and-privacy), [Evaluation](#evaluation), [Accessibility](#accessibility) | needs a person | Done in code; screen-reader testing by a person hasn't been done. |

## Limitations

- Matching by meaning needs the ml extra and about 180 MB of model downloads on first start. Both default models were trained on English text, so they do little for resumes in other languages.
- The real models never run in CI. The tests use a fake encoder and reranker, and the evaluation's threshold sweep (`python -m evals.run --semantic`) hasn't been run with the real models yet, so the default threshold of 0.5 is still untuned.
- Without the ml extra, matching is exact. "Built REST endpoints" counts for REST APIs, but "designed services other teams call" doesn't count for anything.
- With the rule parser, skills outside the 328-skill catalog are marked `not_assessed` (or `adjacent` with matching by meaning), not as gaps. General wording such as "relational databases" or "statistics and model evaluation" isn't matched to the tools or methods a resume names. The Claude parser keeps skills outside the catalog as free-text skills, which are matched only by their exact words.
- Some catalog terms cover several tools: GitHub, GitLab and Bitbucket count as Git, and JUnit and NUnit count as Unit testing. A requirement that names the broad skill ("unit tests with Jest or a similar framework") can be proven by a line that names another tool.
- Product names that are also company or place names (Swift, Flutter, Apex, Cypress) count wherever they appear with a capital, including an employer's name in a role header.
- A version requirement is checked only when it says "or later", "or newer", "and above" or "+" right after the skill ("Angular 12 or later", "Java 11+"). "Angular 12" alone isn't read as a minimum.
- Degree fields are compared by their words and a few families (computing, engineering, mathematics and statistics, sciences, business). A field outside them, or a foreign degree name the rules don't know, is left for a person to check, and a degree listed only in a summary sentence isn't read. Certifications are matched by the vendor or skill they name and their title words, so a certification written without either ("SnowPro Core") counts only when it also names the vendor.
- Total years count every dated role in the experience section, whatever the field. Five years of any work meets "5+ years of experience in data engineering", which is why the next step asks the person to check the kind of work.
- A role is found only when a date range sits on its header line, or on the line after the one to three short lines that hold its title and employer. Dates above the title, a title and employer with no separator between them ("Data Engineer Example Corp"), or an employer and city separated only by a tab can lose or mix up the employer, and roles without dates aren't counted. A year without a month counts from January of the start year to December of the end year, with a warning.
- Company suffixes are a fixed list (Pvt. Ltd., Private Limited, Ltd., Limited, Inc., LLC, LLP, Corp., Corporation, GmbH, Technologies, Solutions, Consulting, Services, Systems, Infotech, Softech). A firm named without one is still placed by word order and job-title words, and a line that runs a title into a firm with a legal suffix ("Data Engineer Example Corp") is read as an employer.
- A "Client:" line is never the employer, so a role that names only its client has no employer.
- Places are recognized from a fixed list: US states and their codes, Canadian provinces, the larger Indian states, about 40 countries and the work modes ("Remote", "Hybrid"). A city is dropped only together with one of them.
- In a resume without an experience heading, roles are read from the lines with date ranges. A dated line that isn't a job (a course, an award) can become a role there, and a role whose dates can't be read is lost.
- Years requirements cite no resume lines in the report, only the years counted, so a reader has to look at the role list to see where they came from.
- Measurable results are found with patterns. Numbers written as words ("two teams") are missed, and a number right after a capitalized word ("Python 3", "Tier 1") is skipped as a likely version.
- Education parsing is best effort. It looks for words such as "University", "College", "B.S." or "Master".
- The screen's tests cover login, registration, logout, account deletion and the consent form's errors, but not uploading a file, which Streamlit's test runner can't do. The upload path is tested through the same helper functions against the API. They need Streamlit, which only CI's `ui` job installs.
- The ml extra isn't hash-locked, so an image built with `INSTALL_ML=true` gets whatever versions are current at build time.
- Two-column PDFs are read in the order the PDF stores its text. That's usually column by column, but not always.
- PDF extraction joins a line to the paragraph above it when the line above runs to the right margin. A line in bold after a regular one, or a short line with a date range, starts a new line instead, but a regular header without dates after a full-width line can still be joined to it.
- Scanned resumes (images of text) and old `.doc` files are rejected with a message saying why.
- The job-description parser is rule-based. A heading with no known word that neither ends in a colon nor is written in capitals doesn't end the section above it, and benefit or legal wording that isn't on its lists is kept as a requirement. A prose sentence about the company that names a tool, or that addresses the candidate, is kept as context.
- Employment terms and intro sentences are found by fixed patterns. "W2" or "1099" in a line about tax forms or payroll stays a requirement. A sentence that joins a term to a skill or years ("3+ years of Go; must be authorized to work in the US") stays a requirement, so its skill and years are scored, and is also listed as a term. An intro sentence that states years or says "must" or "required" is kept as it is labeled.
- Section order advice counts only exact, demonstrated evidence, not related lines from matching by meaning. A project is a line in a projects section with the bullets under it, and the 8-tool line for `skills_first` is a choice, not a measured value.
- Metric questions pick bullets with the same patterns that find measurable results, so a bullet whose number those patterns miss can still get one, and a bullet with a number written as a word gets none.
- The API can't know that a person read the consent notice. It records that the client sent `consent=true` and which notice version the server served.
- The match report's HTML is checked with an HTML parser, not in each browser or with assistive technology (see [Accessibility](#accessibility)).
- No real API calls were made while building v0.3 through v1.0, in development or in CI. Both prompts, the structured output and the token limits are tested only against a fake client and a mocked SDK transport, so the first real runs may show prompt problems the tests can't.
- The quality of rewrite suggestions depends on the model. The fact checker only removes rewrites that add facts; it can't make a weak rewrite good.
- The fact checker is rule-based. It rejects some good rewrites, for example "ran the team's design reviews" becoming "led the team's design reviews", because "led" is on its list of bigger claims, "AKS" spelled out as "Azure Kubernetes Service", or "K8s" written as "Kubernetes" (the catalog files K8s and AKS under Kubernetes). It also misses some changes: it compares numbers, dates, names, skills, certifications and a fixed list of scope words, so a changed ordinary word ("claims" becoming "policies") or an added lowercase tool outside the catalog passes.
- Claude's job-description output is only accepted when each requirement is copied word for word. A model that paraphrases loses those requirements, and when none is left the rules take over.
- Corrections are your own text and are not fact checked.
- The Word file is rebuilt from the lines the app read, so the original's fonts, bold words inside lines, links and layout aren't kept, and a two-column PDF comes out in the order the app read it. Check the extracted lines and fix them before exporting.
- Suggestions are made during the request. With the default allowance of 20, asking for every eligible requirement can mean up to 10 calls to Claude, and the request waits for all of them. Two requests for the same analysis at the same moment can each use the remaining allowance.
- No email is sent. An account's email is never confirmed, so it is a login name rather than proof of who someone is, and a forgotten password needs the operator (`python -m app.admin reset-password`).
- Rate limits are kept in the memory of each API process. They reset at a restart and would multiply with more than one replica, so the Azure template runs exactly one. Visitors who reach the API through the screen share the screen's address for the per-address limits unless the screen's address is in `TRUSTED_PROXIES`; the per-account limits still apply to each person.
- One replica of the API is also one point of failure: while it restarts, or while ClamAV loads its signatures, the API isn't ready.
- ClamAV needs about 3 GB of memory, which is most of the steady cost of a deployment. In the Azure template its signatures aren't kept on a volume, so each new revision starts from the ones in the image and updates them.
- The Azure template is checked with the Bicep CLI against Azure's resource schemas, but the project hasn't deployed it. The Postgres tests, the Docker smoke test and the image builds run only in GitHub Actions, and were written without a local Docker, Postgres or ClamAV to try them on.
- The database connection uses `sslmode=require`, which encrypts it but doesn't check the server's certificate.

## Roadmap

| Version | Focus |
| --- | --- |
| 0.1 | Extraction, job-description parsing, exact matching, API, tests, CI (done) |
| 0.2 | Matching by meaning with sentence-transformers (search, then rerank) and the adjacent status. Each job's title, employer, dates and measurable results, years of experience, and years requirements. Streamlit screen and docker compose. (done) |
| 0.3 | Claude-based job-description parsing and bullet rewrites behind the same interfaces. A fact checker that rejects any rewrite adding a number, date, employer or tool not in the source line. Side-by-side edits, correction of extraction mistakes, gap questions and DOCX export. (done) |
| 0.4 | Hand-labeled evaluation set of fictional resumes and job descriptions, and a runner (`python -m evals.run`) that measures role and date extraction, requirement extraction and priorities, statuses, gap precision and recall, the false proven rate, evidence recall at 1 and 3, and the fact checker on a held-out set. Results record the pipeline version so runs can be compared across versions, and CI fails when a metric drops below its threshold. (done. The threshold sweep for matching by meaning and the Claude measurements are built but haven't been run with the real models or API, so the threshold is still untuned.) |
| 0.5 | Fixes for the failure patterns found by the evaluation: more role header layouts, places after the employer, roles and degrees in resumes without headings, PDF lines joined to the line above, job-description headings and boilerplate, 221 more catalog skills, degree and certification requirements, and version requirements. The PDF builder keeps en dashes, and `--data-dir` runs the evaluation on another labeled set. (done. Development-set numbers are optimistic; the held-out results are in [Evaluation](#evaluation).) |
| 1.0 | Accounts with argon2id passwords and hashed session tokens, each person's analyses visible only to them, account deletion. Postgres with Alembic migrations. Malware scanning with ClamAV, rate limits, security headers and production checks. The screen with login. docker compose with the whole stack, an Azure Container Apps template and guide, release and deploy workflows, and a demo video script. Consent before an upload and for Claude, section order advice, metric questions, a downloadable match report, an accessibility pass, document quality and a human rating sheet in the evaluation, and three reading fixes (company suffixes and clients, employment terms, intro sentences). (done, this release. The Azure template is checked with the Bicep CLI but hasn't been deployed by the project yet, and the items marked "needs your API key" or "needs a person" in [Specification coverage](#specification-coverage) are open.) |

Ideas for after 1.0, in no fixed order and not promised:

- Email: confirming addresses and a "forgot my password" link, which needs a mail provider.
- A shared store for the rate limits (Postgres or Redis), so the API can run more than one replica.
- Single sign-on with OpenID Connect, and a second factor for password logins.
- A private network for the database, `sslmode=verify-full`, and a volume for ClamAV's signatures.
- Running the real models and Claude against the evaluation sets, tuning the threshold for matching by meaning with the results, and reviewing the generated candidates.
- A person rating the evidence sheet, and screen-reader testing by a person.
- A new held-out set, since the current one was read once for the v1.0 fixes.
- Resumes exported from Word and Google Docs, and two-column layouts, in the evaluation set.
- A list of earlier analyses on the screen (the API already has `GET /api/v1/analyses`).

## License

AGPL-3.0-or-later. PDF extraction uses [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed under the AGPL, so this project is too. If you run a modified version as a public service, you must make its source available to its users.

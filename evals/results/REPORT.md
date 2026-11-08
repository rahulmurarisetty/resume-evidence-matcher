# Evaluation report

Run date: 2026-11-08

Written by `python -m evals.run` from `latest.json` in this folder. Every number comes from the hand-labeled fictional set in `evals/data/`, read through the app's own pipeline. Each rate is shown with its counts, as (count/total).

## Run

| Setting | Value |
| --- | --- |
| Pipeline version | 0.4.0-exact |
| Git commit | 8582174 with uncommitted changes |
| Labels as of | 2026-11-01, passed to the app as today |
| Job parser | rules (Claude only with --llm) |
| Matching | exact |
| Matching by meaning (--semantic) | not requested |
| Claude parser and rewrites (--llm) | not requested |
| Libraries | Python 3.13.18, PyMuPDF 1.28.2, python-docx 1.2.0 |
| Labels | 12 resumes (35 roles, 15 education entries), 8 jobs (121 requirement lines), 16 pairs (176 requirement labels), 40 held-out and 60 development fact-check cases |

| Format | How the file is made |
| --- | --- |
| `pdf_inline` | PDF with the default PdfStyle: bullet glyph and text in one text run |
| `pdf_separate` | PDF with bullet_mode="separate": the glyph drawn on its own, as Word exports do |
| `docx` | DOCX from python-docx: Heading 1 sections and List Bullet paragraphs |

"Overall" pools the formats. The same resumes are read in each format, so it is not that many independent samples: a resume that fails in every format counts once per format.

## Headline numbers

| Metric | Result |
| --- | --- |
| Role detection recall (all formats) | 78.1% (82/105) |
| Total years within 0.5 of the label | 72.2% (26/36) |
| Requirement extraction recall | 100.0% (121/121) |
| Requirement extraction precision | 88.3% (121/137) |
| Priority accuracy on extracted requirements | 90.9% (110/121) |
| Pair status accuracy (all formats) | 68.6% (362/528) |
| False proven: app says direct, label says gap or needs_check | 0.0% (0/174) |
| Evidence recall@3 | 57.6% (204/354) |
| Fact checker accuracy, held-out set | 97.5% (39/40) |
| Fact checker false passes, held-out set | 0.0% (0/20) |

## Resume structure

A predicted role matches a labeled role when both its title and its employer match (equal after normalizing case and punctuation, or a fuzzy ratio of at least 0.85). Months are compared on matched roles. Total years counts as within 0.5 only when the app gives a number.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Role precision | 93.1% (27/29) | 93.1% (27/29) | 93.3% (28/30) | 93.2% (82/88) |
| Role recall | 77.1% (27/35) | 77.1% (27/35) | 80.0% (28/35) | 78.1% (82/105) |
| Start month correct (matched roles) | 88.9% (24/27) | 88.9% (24/27) | 100.0% (28/28) | 92.7% (76/82) |
| End month correct (matched roles) | 92.6% (25/27) | 92.6% (25/27) | 100.0% (28/28) | 95.1% (78/82) |
| Resumes with total years read | 83.3% (10/12) | 83.3% (10/12) | 91.7% (11/12) | 86.1% (31/36) |
| Total years within 0.5 | 66.7% (8/12) | 66.7% (8/12) | 83.3% (10/12) | 72.2% (26/36) |
| Total years mean absolute error (resumes with a value) | 1.07 | 1.07 | 0.84 | 0.99 |
| Education recall | 86.7% (13/15) | 86.7% (13/15) | 93.3% (14/15) | 88.9% (40/45) |
| Education precision | 100.0% (13/13) | 100.0% (13/13) | 100.0% (14/14) | 100.0% (40/40) |
| Education year correct (matched entries) | 92.3% (12/13) | 92.3% (12/13) | 100.0% (14/14) | 95.0% (38/40) |

Per resume, with one value per format (pdf_inline / pdf_separate / docx):

| Resume | Labeled roles | Roles matched | Labeled years | Years read |
| --- | --- | --- | --- | --- |
| r01_data_engineer | 3 | 3 / 3 / 3 | 8.9 | 8.9 / 8.9 / 8.9 |
| r02_dotnet_fullstack | 3 | 3 / 3 / 3 | 9.9 | 9.9 / 9.9 / 9.9 |
| r03_react_frontend | 3 | 3 / 3 / 3 | 7.9 | n/a / n/a / 7.9 |
| r04_ml_engineer | 3 | 3 / 3 / 3 | 7.6 | 7.6 / 7.6 / 7.6 |
| r05_devops_sre | 3 | 3 / 3 / 3 | 8.9 | 8.9 / 8.9 / 8.9 |
| r06_qa_automation | 3 | 3 / 3 / 3 | 8.5 | 8.5 / 8.5 / 8.5 |
| r07_data_analyst | 2 | 2 / 2 / 2 | 7.6 | 7.6 / 7.6 / 7.6 |
| r08_guidewire_developer | 3 | 1 / 1 / 2 | 8.4 | 6.9 / 6.9 / 8.4 |
| r09_java_backend | 3 | 0 / 0 / 0 | 10.5 | 1.3 / 1.3 / 1.3 |
| r10_python_backend | 3 | 0 / 0 / 0 | 7.4 | n/a / n/a / n/a |
| r11_cloud_data_architect | 4 | 4 / 4 / 4 | 13.3 | 13.3 / 13.3 / 13.3 |
| r12_junior_developer | 2 | 2 / 2 / 2 | 1.6 | 1.6 / 1.6 / 1.6 |

## Requirement extraction

Extracted requirement texts are matched one to one with the labeled lines after normalizing case, whitespace and punctuation: equal, one containing the other, or a fuzzy ratio of at least 0.85. The job descriptions are plain text, so these numbers don't depend on the resume format.

| Metric | rules |
| --- | --- |
| Extraction precision (extracted items that are labeled lines) | 88.3% (121/137) |
| Extraction recall (labeled lines found) | 100.0% (121/121) |
| Priority accuracy on matched items | 90.9% (110/121) |
| Job minimum years correct | 100.0% (8/8) |
| Job title correct | 100.0% (8/8) |

Rule parser matches: 121 exact, 0 by containment, 0 fuzzy.

Per class, counting lines that weren't extracted against recall and extracted lines that aren't requirements against precision:

| Class | Precision | Recall |
| --- | --- | --- |
| required | 100.0% (46/46) | 82.1% (46/56) |
| preferred | 72.1% (31/43) | 96.9% (31/32) |
| context | 68.8% (33/48) | 100.0% (33/33) |

Confusion matrix for the rule parser (rows are labels, columns the parser's priority; not_a_requirement rows are extracted lines with no label):

| label \ app | required | preferred | context | not_extracted |
| --- | --- | --- | --- | --- |
| required | 46 | 1 | 9 | 0 |
| preferred | 0 | 31 | 1 | 0 |
| context | 0 | 0 | 33 | 0 |
| not_a_requirement | 0 | 11 | 5 | 0 |

Per job:

| Job | Labeled lines | Extracted | Matched | Priority correct | Min years (label / app) | Title correct |
| --- | --- | --- | --- | --- | --- | --- |
| j01_senior_data_engineer | 16 | 24 | 16 | 15 | 5 / 5 | yes |
| j02_dotnet_fullstack_developer | 15 | 17 | 15 | 15 | 3 / 3 | yes |
| j03_frontend_react_engineer | 12 | 12 | 12 | 7 | 4 / 4 | yes |
| j04_ml_engineer | 15 | 16 | 15 | 10 | 4 / 4 | yes |
| j05_site_reliability_engineer | 17 | 19 | 17 | 17 | 5 / 5 | yes |
| j06_qa_automation_engineer | 15 | 15 | 15 | 15 | 3 / 3 | yes |
| j07_backend_java_developer | 15 | 16 | 15 | 15 | 5 / 5 | yes |
| j08_guidewire_policycenter_developer | 16 | 18 | 16 | 16 | 6 / 6 | yes |

## Evidence and status per pair

Each labeled requirement in pairs.json is looked up in the app's report through the same text matching as above. The app's statuses map to the labels one to one, with not_assessed read as needs_check; a labeled requirement the parser didn't extract counts as not_extracted and is always wrong. Evidence recall looks at the first 1 or 3 lines the report cites (exact evidence skill by skill, then related evidence) and counts a hit when a line contains a labeled evidence string or is contained in one. It covers labeled direct, partial and adjacent items that have evidence strings. Years-only requirements cite no lines in the report, so recall is also shown without them.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Status accuracy | 68.2% (120/176) | 68.2% (120/176) | 69.3% (122/176) | 68.6% (362/528) |
| False proven (direct where the label is gap or needs_check) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/174) |
| Share of direct calls that are false proven | 0.0% (0/73) | 0.0% (0/73) | 0.0% (0/75) | 0.0% (0/221) |
| Direct where the label isn't direct | 3.9% (3/78) | 3.9% (3/78) | 3.9% (3/78) | 3.9% (9/234) |
| Gap precision | 87.2% (34/39) | 87.2% (34/39) | 87.2% (34/39) | 87.2% (102/117) |
| Gap recall | 69.4% (34/49) | 69.4% (34/49) | 69.4% (34/49) | 69.4% (102/147) |
| Labeled requirement not extracted | 0.0% (0/176) | 0.0% (0/176) | 0.0% (0/176) | 0.0% (0/528) |
| Evidence recall@1 | 53.4% (63/118) | 53.4% (63/118) | 53.4% (63/118) | 53.4% (189/354) |
| Evidence recall@3 | 57.6% (68/118) | 57.6% (68/118) | 57.6% (68/118) | 57.6% (204/354) |
| Evidence recall@1 without years-only items | 60.6% (63/104) | 60.6% (63/104) | 60.6% (63/104) | 60.6% (189/312) |
| Evidence recall@3 without years-only items | 65.4% (68/104) | 65.4% (68/104) | 65.4% (68/104) | 65.4% (204/312) |

Confusion matrix, all formats (rows are labels, columns the app):

| label \ app | direct | partial | adjacent | gap | needs_check | not_extracted |
| --- | --- | --- | --- | --- | --- | --- |
| direct | 212 | 18 | 0 | 6 | 58 | 0 |
| partial | 3 | 21 | 0 | 0 | 9 | 0 |
| adjacent | 6 | 9 | 0 | 9 | 3 | 0 |
| gap | 0 | 3 | 0 | 102 | 42 | 0 |
| needs_check | 0 | 0 | 0 | 0 | 27 | 0 |

Per status, all formats:

| Status | Precision | Recall |
| --- | --- | --- |
| direct | 95.9% (212/221) | 72.1% (212/294) |
| partial | 41.2% (21/51) | 63.6% (21/33) |
| adjacent | n/a (0/0) | 0.0% (0/27) |
| gap | 87.2% (102/117) | 69.4% (102/147) |
| needs_check | 19.4% (27/139) | 100.0% (27/27) |

Status accuracy by how well the resume fits the job (all formats):

| Fit | Status accuracy |
| --- | --- |
| strong | 72.0% (214/297) |
| mixed | 53.5% (69/129) |
| wrong | 77.5% (79/102) |

Correct statuses per pair, one value per format (pdf_inline / pdf_separate / docx):

| Pair | Fit | Labels | Correct |
| --- | --- | --- | --- |
| r01_data_engineer x j01_senior_data_engineer | strong | 11 | 10 / 10 / 10 |
| r11_cloud_data_architect x j01_senior_data_engineer | strong | 11 | 10 / 10 / 10 |
| r03_react_frontend x j01_senior_data_engineer | wrong | 11 | 8 / 8 / 9 |
| r02_dotnet_fullstack x j02_dotnet_fullstack_developer | strong | 10 | 8 / 8 / 8 |
| r08_guidewire_developer x j02_dotnet_fullstack_developer | mixed | 10 | 6 / 6 / 6 |
| r03_react_frontend x j03_frontend_react_engineer | strong | 9 | 4 / 4 / 5 |
| r12_junior_developer x j03_frontend_react_engineer | mixed | 9 | 4 / 4 / 4 |
| r04_ml_engineer x j04_ml_engineer | strong | 11 | 7 / 7 / 7 |
| r06_qa_automation x j04_ml_engineer | wrong | 11 | 8 / 8 / 8 |
| r05_devops_sre x j05_site_reliability_engineer | strong | 12 | 8 / 8 / 8 |
| r10_python_backend x j05_site_reliability_engineer | mixed | 12 | 5 / 5 / 5 |
| r06_qa_automation x j06_qa_automation_engineer | strong | 11 | 6 / 6 / 6 |
| r09_java_backend x j07_backend_java_developer | strong | 12 | 8 / 8 / 8 |
| r12_junior_developer x j07_backend_java_developer | mixed | 12 | 8 / 8 / 8 |
| r08_guidewire_developer x j08_guidewire_policycenter_developer | strong | 12 | 10 / 10 / 10 |
| r07_data_analyst x j08_guidewire_policycenter_developer | wrong | 12 | 10 / 10 / 10 |

## Fact checker

The positive class is "adds a fact": a rejected rewrite is a positive prediction. A false pass is the dangerous error, because that rewrite would be shown to the person. The held-out set is the primary result. The development set was used while building the checker, so its numbers are optimistic.

| Metric | Held-out set (40 cases) | Development set, used while building the checker, so optimistic (60 cases) |
| --- | --- | --- |
| Accuracy | 97.5% (39/40) | 98.3% (59/60) |
| Precision (rejected rewrites that do add a fact) | 95.2% (20/21) | 96.8% (30/31) |
| Recall (rewrites that add a fact and were rejected) | 100.0% (20/20) | 100.0% (30/30) |
| False passes (adds_fact cases the checker passed) | 0.0% (0/20) | 0.0% (0/30) |
| False rejects (faithful cases the checker rejected) | 5.0% (1/20) | 3.3% (1/30) |

### Held-out set by category

| Category | Label | Correct |
| --- | --- | --- |
| added_certification | adds_fact | 100.0% (2/2) |
| added_date | adds_fact | 100.0% (2/2) |
| added_employer | adds_fact | 100.0% (3/3) |
| added_number | adds_fact | 100.0% (3/3) |
| added_result | adds_fact | 100.0% (2/2) |
| added_scope | adds_fact | 100.0% (2/2) |
| added_tool | adds_fact | 100.0% (3/3) |
| changed_number | adds_fact | 100.0% (3/3) |
| faithful_reorder | faithful | 100.0% (3/3) |
| faithful_reword | faithful | 100.0% (5/5) |
| faithful_trim | faithful | 100.0% (4/4) |
| tricky_faithful | faithful | 87.5% (7/8) |

### Development set by category (used while building the checker, so optimistic)

| Category | Label | Correct |
| --- | --- | --- |
| added_certification | adds_fact | 100.0% (3/3) |
| added_date | adds_fact | 100.0% (3/3) |
| added_employer | adds_fact | 100.0% (3/3) |
| added_number | adds_fact | 100.0% (5/5) |
| added_scope | adds_fact | 100.0% (5/5) |
| added_tool | adds_fact | 100.0% (5/5) |
| changed_number | adds_fact | 100.0% (6/6) |
| faithful_reorder | faithful | 100.0% (5/5) |
| faithful_reword | faithful | 83.3% (5/6) |
| faithful_trim | faithful | 100.0% (5/5) |
| tricky_faithful | faithful | 100.0% (14/14) |

### Every disagreement

ho010 (held-out set, tricky_faithful): labeled faithful, the checker rejected it.

- Source: Moved nightly batch workers from EC2 instances to K8s CronJobs.
- Rewrite: Moved nightly batch workers from EC2 instances to Kubernetes CronJobs.
- Added facts in the label: none
- The checker's reasons: "Kubernetes" looks like the name of an organization or product that isn't in the original line.

fc057 (development set, faithful_reword): labeled faithful, the checker rejected it.

- Source: Mentored 4 developers and ran the team's design review meetings.
- Rewrite: Mentored four developers and led the team's design review meetings.
- Added facts in the label: none
- The checker's reasons: "led" claims more responsibility than the original line does.

## Matching by meaning

Not run in this evaluation, because --semantic wasn't given. In exact mode the app never returns adjacent, so every item labeled adjacent counts as an error above. Install the ml extra (pip install -e ".[dev,ml]", with the CPU-only PyTorch first on Linux as the README shows), then run python -m evals.run --semantic. The first run downloads the two models from Hugging Face, about 180 MB.

## Claude parser and rewrites

Not run in this evaluation, because --llm wasn't given. No call was made to a model provider. Put ANTHROPIC_API_KEY in the environment or in a local .env file (see the README), then run python -m evals.run --llm. It makes one parse call per job and up to LLM_MAX_SUGGESTIONS rewrite candidates per pair (20 by default).

## Error analysis

Each pattern below is a rule over the default run's failures, and patterns are listed most frequent first. A count is of distinct labeled items: an item that fails in several formats counts once, and the formats are named. The text says what was observed in the extracted lines and reports, not a confirmed root cause.

### Requirements that name no catalog skill are left for a person to check

Pair status: 35 labeled requirements, all formats. The rule parser only finds skills from the skill catalog. A requirement whose tools are outside it, or that asks for a domain, a degree or a certification, gets no skills, so exact matching marks it needs_check whether the resume proves it, lacks it or shows it in part.

- r02_dotnet_fullstack x j02_dotnet_fullstack_developer (all formats): "Experience with RxJS and NgRx": labeled partial; the parser found no catalog skill in it.
- r03_react_frontend x j03_frontend_react_engineer (all formats): "Experience with Next.js or another server-side rendering framework is required.": labeled direct; the parser found no catalog skill in it.
- r04_ml_engineer x j04_ml_engineer (all formats): "Solid understanding of statistics and model evaluation": labeled direct; the parser found no catalog skill in it.

### Years requirements cite no resume lines

Evidence: 14 labeled requirements, all formats. For a years-only requirement the report gives the years it counted but no lines, while the labels cite the role header lines. These items always miss in evidence recall, which is why recall is also shown without them.

- r01_data_engineer x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (8.9 years read).
- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (13.3 years read).
- r03_react_frontend x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (no years read).

### Required lines get the wrong priority

Requirement extraction: 11 job lines. Required lines written as prose sentences, or under a heading the parser doesn't know, default to context; a line-level word such as "Familiarity with" turns a required line into preferred.

- j01_senior_data_engineer: "Familiarity with Git and CI/CD workflows" labeled required, parsed as preferred.
- j03_frontend_react_engineer: "We are looking for someone with 4+ years of professional front-end development experience." labeled required, parsed as context.
- j04_ml_engineer: "Experience with PyTorch or TensorFlow" labeled required, parsed as context.

### Benefits, pay and legal lines after an unknown heading are kept as requirements

Requirement extraction: 10 job lines. A heading the parser doesn't know ("What we offer") doesn't end the section above it, so benefit, salary, equal opportunity and how-to-apply lines are kept with that section's priority.

- j01_senior_data_engineer: "Salary range: $150,000 - $175,000 plus annual bonus" kept as preferred.
- j05_site_reliability_engineer: "Compensation: $160,000 - $190,000 base, plus equity." kept as preferred.
- j08_guidewire_policycenter_developer: "Excellent compensation and benefits. Example Coastal Insurance is an Equal Opportunity Employer. Please sha..." kept as preferred.

### Related experience needs matching by meaning

Pair status: 9 labeled requirements, all formats. In exact mode the app never returns adjacent, so related experience the labels mark adjacent (GitLab CI for GitHub Actions, Java for C#) comes out as gap, partial or needs_check. Matching by meaning is meant for these and wasn't run.

- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "Experience with GitHub Actions": labeled adjacent, app gap (GitHub Actions missing, Git missing).
- r03_react_frontend x j01_senior_data_engineer (all formats): "Experience with GitHub Actions": labeled adjacent, app partial (GitHub Actions missing, Git demonstrated).
- r02_dotnet_fullstack x j02_dotnet_fullstack_developer (all formats): "Knowledge of Guidewire or other insurance platforms": labeled adjacent, app partial (Guidewire missing, Insurance listed).

### The status is right but the first lines cited aren't the labeled ones

Evidence: 7 labeled requirements, all formats. The status matches the label, but none of the report's first three lines is a labeled evidence line. Evidence is listed skill by skill, so the first lines can all come from one skill of the requirement, or from a broad skill such as ETL (matched by "data pipelines").

- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "Experience building data pipelines on AWS or Azure": labeled direct, app direct; first line: experience line "Implemented CI/CD for data pipelines with Azure DevOps." (ETL via 'data pipelines').
- r04_ml_engineer x j04_ml_engineer (all formats): "Healthcare or insurance data experience": labeled direct, app direct; first line: experience line "Data Scientist - Demo Insurance Group - May 2019 to Jul 2021" (Insurance via 'Insurance').
- r08_guidewire_developer x j08_guidewire_policycenter_developer (all formats): "Guidewire certification (Associate or Specialist)": labeled direct, app direct; first line: experience line "Senior Guidewire Developer, Example Mutual, Jacksonville, FL | Apr 2022 - Till date" (Guidewire via 'Guidewire').

### Years requirements fail when roles weren't read

Pair status: 5 labeled requirements, all formats. A years requirement is decided from the roles the app read: their total for "5+ years of experience", and the roles that mention the skill for "4+ years with Java". When a role is lost (see the structure patterns) the years fall short and the requirement becomes a gap or partial, or needs_check when no role was read at all.

- r03_react_frontend x j01_senior_data_engineer (pdf_inline, pdf_separate): "5+ years of professional software or data engineering experience": labeled direct, app needs_check with no years read in total.
- r10_python_backend x j05_site_reliability_engineer (all formats): "5+ years of experience in software engineering, DevOps or systems administration": labeled direct, app needs_check with no years read in total.
- r09_java_backend x j07_backend_java_developer (all formats): "5+ years of backend software development experience": labeled direct, app gap with 1.3 years read in total.

### Work the labels count as shown is found only in a summary or skills line

Pair status: 5 labeled requirements, all formats. The labels count the work as shown in a bullet, but the bullet describes it in other words, so exact matching finds the skill only in the summary or skills section, or not at all, and calls the requirement partial.

- r01_data_engineer x j01_senior_data_engineer (all formats): "Background in the insurance industry": labeled direct, app partial (Insurance listed).
- r03_react_frontend x j01_senior_data_engineer (all formats): "Familiarity with Git and CI/CD workflows": labeled direct, app partial (Git demonstrated, CI/CD missing).
- r04_ml_engineer x j04_ml_engineer (all formats): "Hands-on NLP experience, including transformer models": labeled direct, app partial (NLP listed).

### A resume without section headings yields no roles or education

Resume structure: 4 roles or entries, all formats. Roles are read only from an experience section and education only from an education section. With no headings every line is in the header section, so no role, date, total years or degree is read.

- r10_python_backend (all formats): role 'Backend Developer, Sample Retail Group': The line is in the header section, and roles are only read from an experience section. Extracted line: "Backend Developer, Sample Retail Group | Feb 2023 - Present".
- r10_python_backend (all formats): role 'Python Developer, Demo Startup Labs': The line is in the header section, and roles are only read from an experience section. Extracted line: "Python Developer, Demo Startup Labs | Apr 2020 - Jan 2023".
- r10_python_backend (all formats): role 'Junior Developer, Placeholder Web Studio': The line is in the header section, and roles are only read from an experience section. Extracted line: "Junior Developer, Placeholder Web Studio | Jul 2019 - Mar 2020".

### Company and posting details are kept as requirements

Requirement extraction: 4 job lines. Company descriptions and posting lines (company, client) are kept as context requirements: before the first heading when they name a catalog skill (a company name with "Insurance" in it), and inside a role section as one more sentence.

- j02_dotnet_fullstack_developer: "Company: Sample Insurance Holdings" kept as context.
- j07_backend_java_developer: "Demo Freight Systems is growing the team that runs our order and shipment platform." kept as context.
- j08_guidewire_policycenter_developer: "Client: Example Coastal Insurance" kept as context.

### Date ranges with a separator the parser doesn't accept are not read

Resume structure: 3 roles or entries, pdf_inline, pdf_separate. The extracted header has a character between the two dates that the date pattern doesn't accept, so the role's months aren't counted.

- r03_react_frontend (pdf_inline, pdf_separate): role 'Senior Front-End Engineer, Sample Retail Group': The role was found, but its dates couldn't be read. Between the file and the extracted text, '–' became '·'. Extracted line: "Senior Front-End Engineer at Sample Retail Group, Mar 2022 · Present".
- r03_react_frontend (pdf_inline, pdf_separate): role 'Front-End Developer, Demo Media': The role was found, but its dates couldn't be read. Between the file and the extracted text, '–' became '·'. Extracted line: "Front-End Developer at Demo Media, Jun 2019 · Feb 2022".
- r03_react_frontend (pdf_inline, pdf_separate): role 'Web Developer Intern, Example Agency': The role was found, but its dates couldn't be read. Between the file and the extracted text, '–' became '·'. Extracted line: "Web Developer Intern at Example Agency, Jan 2019 · May 2019".

### PDF extraction joins a line to the one before it

Resume structure: 3 roles or entries, pdf_inline, pdf_separate. A line that follows a full-width line, or any line on a page with only short lines, is joined to the previous paragraph, so a role header or an education entry disappears into another line.

- r08_guidewire_developer (pdf_inline, pdf_separate): role 'Software Engineer, Demo Tech Solutions': The header was joined with a neighbouring line during extraction. Extracted line: "Environment: Guidewire BillingCenter 9, CustomerEngage, Gosu, Angular, SQL Server, Bitbucket, Jira Software...".
- r11_cloud_data_architect (pdf_inline, pdf_separate): education 'B.Tech Electronics': The entry was joined with a neighbouring line during extraction. Extracted line: "M.S. Information Technology, Example University, 2013 B.Tech Electronics, Sample Institute of Technology, 2011".
- r11_cloud_data_architect (pdf_inline, pdf_separate): education 'M.S. Information Technology': Read the year 2011, labeled 2013. Extracted line: "M.S. Information Technology, Example University, 2013 B.Tech Electronics, Sample Institute of Technology, 2011".

### A related skill or a missing detail is counted as direct proof

Pair status: 3 labeled requirements, all formats. The catalog files some tools under a broader skill (GitHub, GitLab and Bitbucket are terms for Git, JUnit for Unit testing), so a requirement for one tool can be proven by a line that names another. A version the requirement asks for isn't checked either.

- r08_guidewire_developer x j02_dotnet_fullstack_developer (all formats): "Experience with Angular 12 or later": labeled partial, app direct from the experience line "Customized CustomerEngage Angular screens for policy servicing and online payments." (Angular via 'Angular').
- r12_junior_developer x j03_frontend_react_engineer (all formats): "You should be comfortable writing unit tests with Jest or a similar framework.": labeled adjacent, app direct from the experience line "Wrote JUnit tests for the endpoint and fixed 12 bugs from the team backlog." (Unit testing via 'JUnit').
- r08_guidewire_developer x j02_dotnet_fullstack_developer (all formats): "Experience with Azure DevOps or GitHub Actions": labeled adjacent, app direct from the experience line "Environment: Guidewire PolicyCenter 10, Guidewire Cloud, Gosu, PCF, SOAP, REST, Jenkins..." (Git via 'Git').

### Roles are found but the title or employer is split wrongly

Resume structure: 2 roles or entries, all formats. The role and its dates are read, but extra text stays in the employer (a city and state) or the employer stays in the title, so the role doesn't match its label.

- r08_guidewire_developer (all formats): role 'Senior Guidewire Developer, Example Mutual': Read as a role with title 'Senior Guidewire Developer' and employer 'Example Mutual, Jacksonville, FL'. Extracted line: "Senior Guidewire Developer, Example Mutual, Jacksonville, FL | Apr 2022 - Till date".
- r09_java_backend (all formats): role 'Associate Developer, Sample Software Co': Read as a role with title 'Sample Software Co: Associate Developer' and employer None. Extracted line: "Sample Software Co: Associate Developer, Jun 2016 - Aug 2017".

### Role header lines in some layouts are read as body text

Resume structure: 2 roles or entries, all formats. The line holds a date range the app can read, but it isn't taken as a role header, so the role and its months are lost.

- r09_java_backend (all formats): role 'Senior Software Engineer, Demo Logistics': The line was kept as body text, not read as a role. It starts with words followed by a colon. Extracted line: "Demo Logistics: Senior Software Engineer, May 2021 - present".
- r09_java_backend (all formats): role 'Java Developer, Example Mutual': The line was kept as body text, not read as a role. It starts with words followed by a colon. Extracted line: "Example Mutual: Java Developer, Sep 2017 - Apr 2021".

### Unknown section headings are kept as requirements

Requirement extraction: 2 job lines. A heading the parser doesn't recognize ("What we need:", "What we offer") is kept as a requirement line, and the lines under it keep the previous section's priority.

- j01_senior_data_engineer: "What we offer" kept as preferred.
- j04_ml_engineer: "What we need:" kept as context.

### Faithful rewrites rejected by the fact checker

Fact checker: 2 cases. The checker errs toward rejecting. A leadership word ("led" for "ran") counts as a bigger claim, and another catalog name for the same skill ("Kubernetes" for "K8s") counts as a new product name.

- holdout ho010: "Moved nightly batch workers from EC2 instances to K8s CronJobs." became "Moved nightly batch workers from EC2 instances to Kubernetes CronJobs.": labeled faithful, checker rejected ("Kubernetes" looks like the name of an organization or product that isn't in the original line.).
- development fc057: "Mentored 4 developers and ran the team's design review meetings." became "Mentored four developers and led the team's design review meetings.": labeled faithful, checker rejected ("led" claims more responsibility than the original line does.).

## Known weaknesses of this evaluation

- The sample is small: 12 resumes, 8 job descriptions, 16 pairs with 176 requirement labels, and 100 fact-check cases. One item moves a per-format pair rate by about half a point and a per-job rate by several points, and the three formats read the same resumes, so pooling them doesn't add independent evidence.
- The labels were written by the project team, alongside the fictional resumes and job descriptions, by people who know how the app works. The resumes are cleaner and more regular than real ones, and the labeling conventions in evals/data/README.md decide many borderline items (for example that every soft-skill line is needs_check and that an Environment line counts as work experience).
- The fact checker's development set was used while the checker was built, so its numbers are optimistic. The held-out set is the primary result, but it has 40 cases and was written by the same team.
- Matching by meaning and the Claude parser and rewrites are not run in CI, and were not run for this report unless the run table says so. Exact mode can't produce adjacent, and the Claude path is only exercised against a fake client in the tests.
- Every PDF comes from one builder (tests/builders.py) with a base-14 font that can only encode Latin-1 characters, so an en dash is written into the PDF as a middle dot. Real exports from Word, Google Docs or LaTeX, two-column layouts, tables and text boxes are not covered.
- The evaluation's own matching rules (a fuzzy ratio of 0.85, containment for requirement texts, strict title and employer matching for roles) are choices. Other rules would move some role and requirement matches.

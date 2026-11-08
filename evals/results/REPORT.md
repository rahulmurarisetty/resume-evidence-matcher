# Evaluation report: development set

Run date: 2026-11-08

Written by `python -m evals.run` from `latest.json` in this folder. Every number comes from the hand-labeled fictional set in `evals/data/`, read through the app's own pipeline. Each rate is shown with its counts, as (count/total). This is the development set, which was used to find and fix the failures v0.5 addresses, so its numbers are optimistic.

## Run

| Setting | Value |
| --- | --- |
| Dataset | development (`evals/data`) |
| Pipeline version | 0.5.0-exact |
| Git commit | 6b763ac with uncommitted changes |
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
| Role detection recall (all formats) | 100.0% (105/105) |
| Total years within 0.5 of the label | 100.0% (36/36) |
| Requirement extraction recall | 100.0% (121/121) |
| Requirement extraction precision | 100.0% (121/121) |
| Priority accuracy on extracted requirements | 100.0% (121/121) |
| Pair status accuracy (all formats) | 90.3% (477/528) |
| False proven: app says direct, label says gap or needs_check | 0.0% (0/174) |
| Evidence recall@3 | 74.6% (264/354) |
| Fact checker accuracy, held-out set | 97.5% (39/40) |
| Fact checker false passes, held-out set | 0.0% (0/20) |

## Before and after, development set (used to find and fix these failures, so these numbers are optimistic)

v0.5 was built by reading this set's failures, so its gains here are optimistic. The held-out numbers in the README come from a set that wasn't used for v0.5. Each earlier run is kept in `evals/baselines/development.json`.

- v0.4.0: The committed v0.4 code at 6b763ac, run before any v0.5 change.
- v0.4.0 app, v0.5 PDF builder: The v0.4 app with only the tests/builders.py fix, so en dashes reach the app. This separates the builder fix from the app changes.

| Metric | v0.4.0 | v0.4.0 app, v0.5 PDF builder | This run (0.5.0-exact) |
| --- | --- | --- | --- |
| Role precision (all formats) | 93.2% (82/88) | 93.2% (82/88) | 100.0% (105/105) |
| Role recall (all formats) | 78.1% (82/105) | 78.1% (82/105) | 100.0% (105/105) |
| Start month correct (matched roles) | 92.7% (76/82) | 100.0% (82/82) | 100.0% (105/105) |
| End month correct (matched roles) | 95.1% (78/82) | 100.0% (82/82) | 100.0% (105/105) |
| Total years within 0.5 of the label | 72.2% (26/36) | 77.8% (28/36) | 100.0% (36/36) |
| Education recall | 88.9% (40/45) | 88.9% (40/45) | 100.0% (45/45) |
| Requirement extraction precision | 88.3% (121/137) | 88.3% (121/137) | 100.0% (121/121) |
| Requirement extraction recall | 100.0% (121/121) | 100.0% (121/121) | 100.0% (121/121) |
| Priority accuracy on extracted requirements | 90.9% (110/121) | 90.9% (110/121) | 100.0% (121/121) |
| Pair status accuracy (all formats) | 68.6% (362/528) | 69.3% (366/528) | 90.3% (477/528) |
| False proven | 0.0% (0/174) | 0.0% (0/174) | 0.0% (0/174) |
| Direct where the label isn't direct | 3.9% (9/234) | 3.9% (9/234) | 2.6% (6/234) |
| Gap precision | 87.2% (102/117) | 87.2% (102/117) | 87.0% (141/162) |
| Gap recall | 69.4% (102/147) | 69.4% (102/147) | 95.9% (141/147) |
| Evidence recall@1 | 53.4% (189/354) | 53.4% (189/354) | 69.5% (246/354) |
| Evidence recall@3 | 57.6% (204/354) | 57.6% (204/354) | 74.6% (264/354) |
| Fact checker accuracy, held-out set | 97.5% (39/40) | 97.5% (39/40) | 97.5% (39/40) |
| Fact checker false passes, held-out set | 0.0% (0/20) | 0.0% (0/20) | 0.0% (0/20) |

## Resume structure

A predicted role matches a labeled role when both its title and its employer match (equal after normalizing case and punctuation, or a fuzzy ratio of at least 0.85). Months are compared on matched roles. Total years counts as within 0.5 only when the app gives a number.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Role precision | 100.0% (35/35) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (105/105) |
| Role recall | 100.0% (35/35) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (105/105) |
| Start month correct (matched roles) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (105/105) |
| End month correct (matched roles) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (35/35) | 100.0% (105/105) |
| Resumes with total years read | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 100.0% (36/36) |
| Total years within 0.5 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 100.0% (36/36) |
| Total years mean absolute error (resumes with a value) | 0.00 | 0.00 | 0.00 | 0.00 |
| Education recall | 100.0% (15/15) | 100.0% (15/15) | 100.0% (15/15) | 100.0% (45/45) |
| Education precision | 100.0% (15/15) | 100.0% (15/15) | 100.0% (15/15) | 100.0% (45/45) |
| Education year correct (matched entries) | 100.0% (15/15) | 100.0% (15/15) | 100.0% (15/15) | 100.0% (45/45) |

Per resume, with one value per format (pdf_inline / pdf_separate / docx):

| Resume | Labeled roles | Roles matched | Labeled years | Years read |
| --- | --- | --- | --- | --- |
| r01_data_engineer | 3 | 3 / 3 / 3 | 8.9 | 8.9 / 8.9 / 8.9 |
| r02_dotnet_fullstack | 3 | 3 / 3 / 3 | 9.9 | 9.9 / 9.9 / 9.9 |
| r03_react_frontend | 3 | 3 / 3 / 3 | 7.9 | 7.9 / 7.9 / 7.9 |
| r04_ml_engineer | 3 | 3 / 3 / 3 | 7.6 | 7.6 / 7.6 / 7.6 |
| r05_devops_sre | 3 | 3 / 3 / 3 | 8.9 | 8.9 / 8.9 / 8.9 |
| r06_qa_automation | 3 | 3 / 3 / 3 | 8.5 | 8.5 / 8.5 / 8.5 |
| r07_data_analyst | 2 | 2 / 2 / 2 | 7.6 | 7.6 / 7.6 / 7.6 |
| r08_guidewire_developer | 3 | 3 / 3 / 3 | 8.4 | 8.4 / 8.4 / 8.4 |
| r09_java_backend | 3 | 3 / 3 / 3 | 10.5 | 10.5 / 10.5 / 10.5 |
| r10_python_backend | 3 | 3 / 3 / 3 | 7.4 | 7.4 / 7.4 / 7.4 |
| r11_cloud_data_architect | 4 | 4 / 4 / 4 | 13.3 | 13.3 / 13.3 / 13.3 |
| r12_junior_developer | 2 | 2 / 2 / 2 | 1.6 | 1.6 / 1.6 / 1.6 |

## Requirement extraction

Extracted requirement texts are matched one to one with the labeled lines after normalizing case, whitespace and punctuation: equal, one containing the other, or a fuzzy ratio of at least 0.85. The job descriptions are plain text, so these numbers don't depend on the resume format.

| Metric | rules |
| --- | --- |
| Extraction precision (extracted items that are labeled lines) | 100.0% (121/121) |
| Extraction recall (labeled lines found) | 100.0% (121/121) |
| Priority accuracy on matched items | 100.0% (121/121) |
| Job minimum years correct | 100.0% (8/8) |
| Job title correct | 100.0% (8/8) |

Rule parser matches: 121 exact, 0 by containment, 0 fuzzy.

Per class, counting lines that weren't extracted against recall and extracted lines that aren't requirements against precision:

| Class | Precision | Recall |
| --- | --- | --- |
| required | 100.0% (56/56) | 100.0% (56/56) |
| preferred | 100.0% (32/32) | 100.0% (32/32) |
| context | 100.0% (33/33) | 100.0% (33/33) |

Confusion matrix for the rule parser (rows are labels, columns the parser's priority; not_a_requirement rows are extracted lines with no label):

| label \ app | required | preferred | context | not_extracted |
| --- | --- | --- | --- | --- |
| required | 56 | 0 | 0 | 0 |
| preferred | 0 | 32 | 0 | 0 |
| context | 0 | 0 | 33 | 0 |

Per job:

| Job | Labeled lines | Extracted | Matched | Priority correct | Min years (label / app) | Title correct |
| --- | --- | --- | --- | --- | --- | --- |
| j01_senior_data_engineer | 16 | 16 | 16 | 16 | 5 / 5 | yes |
| j02_dotnet_fullstack_developer | 15 | 15 | 15 | 15 | 3 / 3 | yes |
| j03_frontend_react_engineer | 12 | 12 | 12 | 12 | 4 / 4 | yes |
| j04_ml_engineer | 15 | 15 | 15 | 15 | 4 / 4 | yes |
| j05_site_reliability_engineer | 17 | 17 | 17 | 17 | 5 / 5 | yes |
| j06_qa_automation_engineer | 15 | 15 | 15 | 15 | 3 / 3 | yes |
| j07_backend_java_developer | 15 | 15 | 15 | 15 | 5 / 5 | yes |
| j08_guidewire_policycenter_developer | 16 | 16 | 16 | 16 | 6 / 6 | yes |

## Evidence and status per pair

Each labeled requirement in pairs.json is looked up in the app's report through the same text matching as above. The app's statuses map to the labels one to one, with not_assessed read as needs_check; a labeled requirement the parser didn't extract counts as not_extracted and is always wrong. Evidence recall looks at the first 1 or 3 lines the report cites (exact evidence skill by skill, then related evidence) and counts a hit when a line contains a labeled evidence string or is contained in one. It covers labeled direct, partial and adjacent items that have evidence strings. Years-only requirements cite no lines in the report, so recall is also shown without them.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Status accuracy | 90.3% (159/176) | 90.3% (159/176) | 90.3% (159/176) | 90.3% (477/528) |
| False proven (direct where the label is gap or needs_check) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/58) | 0.0% (0/174) |
| Share of direct calls that are false proven | 0.0% (0/94) | 0.0% (0/94) | 0.0% (0/94) | 0.0% (0/282) |
| Direct where the label isn't direct | 2.6% (2/78) | 2.6% (2/78) | 2.6% (2/78) | 2.6% (6/234) |
| Gap precision | 87.0% (47/54) | 87.0% (47/54) | 87.0% (47/54) | 87.0% (141/162) |
| Gap recall | 95.9% (47/49) | 95.9% (47/49) | 95.9% (47/49) | 95.9% (141/147) |
| Labeled requirement not extracted | 0.0% (0/176) | 0.0% (0/176) | 0.0% (0/176) | 0.0% (0/528) |
| Evidence recall@1 | 69.5% (82/118) | 69.5% (82/118) | 69.5% (82/118) | 69.5% (246/354) |
| Evidence recall@3 | 74.6% (88/118) | 74.6% (88/118) | 74.6% (88/118) | 74.6% (264/354) |
| Evidence recall@1 without years-only items | 78.8% (82/104) | 78.8% (82/104) | 78.8% (82/104) | 78.8% (246/312) |
| Evidence recall@3 without years-only items | 84.6% (88/104) | 84.6% (88/104) | 84.6% (88/104) | 84.6% (264/312) |

Confusion matrix, all formats (rows are labels, columns the app):

| label \ app | direct | partial | adjacent | gap | needs_check | not_extracted |
| --- | --- | --- | --- | --- | --- | --- |
| direct | 276 | 9 | 0 | 6 | 3 | 0 |
| partial | 0 | 33 | 0 | 0 | 0 | 0 |
| adjacent | 6 | 6 | 0 | 15 | 0 | 0 |
| gap | 0 | 3 | 0 | 141 | 3 | 0 |
| needs_check | 0 | 0 | 0 | 0 | 27 | 0 |

Per status, all formats:

| Status | Precision | Recall |
| --- | --- | --- |
| direct | 97.9% (276/282) | 93.9% (276/294) |
| partial | 64.7% (33/51) | 100.0% (33/33) |
| adjacent | n/a (0/0) | 0.0% (0/27) |
| gap | 87.0% (141/162) | 95.9% (141/147) |
| needs_check | 81.8% (27/33) | 100.0% (27/27) |

Status accuracy by how well the resume fits the job (all formats):

| Fit | Status accuracy |
| --- | --- |
| strong | 92.9% (276/297) |
| mixed | 81.4% (105/129) |
| wrong | 94.1% (96/102) |

Correct statuses per pair, one value per format (pdf_inline / pdf_separate / docx):

| Pair | Fit | Labels | Correct |
| --- | --- | --- | --- |
| r01_data_engineer x j01_senior_data_engineer | strong | 11 | 10 / 10 / 10 |
| r11_cloud_data_architect x j01_senior_data_engineer | strong | 11 | 10 / 10 / 10 |
| r03_react_frontend x j01_senior_data_engineer | wrong | 11 | 10 / 10 / 10 |
| r02_dotnet_fullstack x j02_dotnet_fullstack_developer | strong | 10 | 9 / 9 / 9 |
| r08_guidewire_developer x j02_dotnet_fullstack_developer | mixed | 10 | 8 / 8 / 8 |
| r03_react_frontend x j03_frontend_react_engineer | strong | 9 | 9 / 9 / 9 |
| r12_junior_developer x j03_frontend_react_engineer | mixed | 9 | 8 / 8 / 8 |
| r04_ml_engineer x j04_ml_engineer | strong | 11 | 8 / 8 / 8 |
| r06_qa_automation x j04_ml_engineer | wrong | 11 | 10 / 10 / 10 |
| r05_devops_sre x j05_site_reliability_engineer | strong | 12 | 12 / 12 / 12 |
| r10_python_backend x j05_site_reliability_engineer | mixed | 12 | 10 / 10 / 10 |
| r06_qa_automation x j06_qa_automation_engineer | strong | 11 | 11 / 11 / 11 |
| r09_java_backend x j07_backend_java_developer | strong | 12 | 11 / 11 / 11 |
| r12_junior_developer x j07_backend_java_developer | mixed | 12 | 9 / 9 / 9 |
| r08_guidewire_developer x j08_guidewire_policycenter_developer | strong | 12 | 12 / 12 / 12 |
| r07_data_analyst x j08_guidewire_policycenter_developer | wrong | 12 | 12 / 12 / 12 |

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

### Years requirements cite no resume lines

Evidence: 14 labeled requirements, all formats. For a years-only requirement the report gives the years it counted but no lines, while the labels cite the role header lines. These items always miss in evidence recall, which is why recall is also shown without them.

- r01_data_engineer x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (8.9 years read).
- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (13.3 years read).
- r03_react_frontend x j01_senior_data_engineer (all formats): "5+ years of professional software or data engineering experience": labeled direct; the report cites no lines (7.9 years read).

### Related experience needs matching by meaning

Pair status: 9 labeled requirements, all formats. In exact mode the app never returns adjacent, so related experience the labels mark adjacent (GitLab CI for GitHub Actions, Java for C#) comes out as gap, partial or needs_check. Matching by meaning is meant for these and wasn't run.

- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "Experience with GitHub Actions": labeled adjacent, app gap (GitHub Actions missing).
- r03_react_frontend x j01_senior_data_engineer (all formats): "Experience with GitHub Actions": labeled adjacent, app gap (GitHub Actions missing).
- r02_dotnet_fullstack x j02_dotnet_fullstack_developer (all formats): "Knowledge of Guidewire or other insurance platforms": labeled adjacent, app partial (Guidewire missing, Insurance listed).

### The status is right but the first lines cited aren't the labeled ones

Evidence: 5 labeled requirements, all formats. The status matches the label, but none of the report's first three lines is a labeled evidence line. Evidence is listed skill by skill, so the first lines can all come from one skill of the requirement, or from a broad skill such as ETL (matched by "data pipelines").

- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "Experience building data pipelines on AWS or Azure": labeled direct, app direct; first line: experience line "Implemented CI/CD for data pipelines with Azure DevOps." (ETL via 'data pipelines').
- r08_guidewire_developer x j08_guidewire_policycenter_developer (all formats): "Minimum 3 years of hands-on Guidewire PolicyCenter or BillingCenter configuration": labeled direct, app direct; first line: experience line "Configured PolicyCenter 10 for homeowners and dwelling fire lines, including PCF screen..." (PolicyCenter via 'PolicyCenter').
- r11_cloud_data_architect x j01_senior_data_engineer (all formats): "Background in the insurance industry": labeled direct, app direct; first line: experience line "Senior ETL Developer, Demo Insurance Group (Jun 2015 - Feb 2019)" (Insurance via 'Insurance').

### Work the labels count as shown is found only in a summary or skills line

Pair status: 3 labeled requirements, all formats. The labels count the work as shown in a bullet, but the bullet describes it in other words, so exact matching finds the skill only in the summary or skills section, or not at all, and calls the requirement partial.

- r01_data_engineer x j01_senior_data_engineer (all formats): "Background in the insurance industry": labeled direct, app partial (Insurance listed).
- r04_ml_engineer x j04_ml_engineer (all formats): "Hands-on NLP experience, including transformer models": labeled direct, app partial (NLP listed, Transformer models demonstrated).
- r04_ml_engineer x j04_ml_engineer (all formats): "Experience with LLMs and retrieval-augmented generation": labeled direct, app partial (LLMs missing, RAG demonstrated).

### Requirements that name no catalog skill are left for a person to check

Pair status: 2 labeled requirements, all formats. The rule parser only finds skills from the skill catalog. A requirement whose tools or domain are outside it gets no skills, and a degree or certification requirement the app can't judge is left to a person, so exact matching marks it needs_check whether the resume proves it, lacks it or shows it in part.

- r09_java_backend x j07_backend_java_developer (all formats): "Experience mentoring other developers": labeled direct; the parser found no catalog skill in it.
- r12_junior_developer x j07_backend_java_developer (all formats): "Experience mentoring other developers": labeled gap; the parser found no catalog skill in it.

### A related skill or a missing detail is counted as direct proof

Pair status: 2 labeled requirements, all formats. The catalog files some tools under a broader skill as well (JUnit and NUnit also count as Unit testing, GitHub and GitLab as Git), so a requirement that names the broad skill can be proven by a line that names another tool, and a domain word ("payments") counts wherever a work line uses it.

- r12_junior_developer x j03_frontend_react_engineer (all formats): "You should be comfortable writing unit tests with Jest or a similar framework.": labeled adjacent, app direct from the experience line "Wrote JUnit tests for the endpoint and fixed 12 bugs from the team backlog." (Unit testing via 'JUnit').
- r10_python_backend x j05_site_reliability_engineer (all formats): "Experience in payments or financial services": labeled adjacent, app direct from the header line "Integrated a payments provider and SMS notifications into the booking flow." (Payments via 'payments').

### Faithful rewrites rejected by the fact checker

Fact checker: 2 cases. The checker errs toward rejecting. A leadership word ("led" for "ran") counts as a bigger claim, and another catalog name for the same skill ("Kubernetes" for "K8s") counts as a new product name.

- holdout ho010: "Moved nightly batch workers from EC2 instances to K8s CronJobs." became "Moved nightly batch workers from EC2 instances to Kubernetes CronJobs.": labeled faithful, checker rejected ("Kubernetes" looks like the name of an organization or product that isn't in the original line.).
- development fc057: "Mentored 4 developers and ran the team's design review meetings." became "Mentored four developers and led the team's design review meetings.": labeled faithful, checker rejected ("led" claims more responsibility than the original line does.).

## Known weaknesses of this evaluation

- The sample is small: 12 resumes, 8 job descriptions, 16 pairs with 176 requirement labels, and 100 fact-check cases. One item moves a per-format pair rate by about half a point and a per-job rate by several points, and the three formats read the same resumes, so pooling them doesn't add independent evidence.
- The labels were written by the project team, alongside the fictional resumes and job descriptions, by people who know how the app works. The resumes are cleaner and more regular than real ones, and the labeling conventions in evals/data/README.md decide many borderline items (for example that every soft-skill line is needs_check and that an Environment line counts as work experience).
- v0.5 fixed the failure patterns this set showed: role layouts, job-description headings and boilerplate, catalog skills, and degree and certification requirements. The fixes were written as general rules, but they were checked against this set, so its numbers are optimistic. A held-out set is the fair test.
- The fact checker's development set was used while the checker was built, so its numbers are optimistic. The held-out set is the primary result, but it has 40 cases and was written by the same team.
- Matching by meaning and the Claude parser and rewrites are not run in CI, and were not run for this report unless the run table says so. Exact mode can't produce adjacent, and the Claude path is only exercised against a fake client in the tests.
- Every PDF comes from one builder (tests/builders.py). Since v0.5 it embeds the font file, so characters such as the en dash reach the app as written. Real exports from Word, Google Docs or LaTeX, two-column layouts, tables and text boxes are not covered.
- The evaluation's own matching rules (a fuzzy ratio of 0.85, containment for requirement texts, strict title and employer matching for roles) are choices. Other rules would move some role and requirement matches.

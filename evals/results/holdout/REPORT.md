# Evaluation report: holdout set

Run date: 2026-11-08

Written by `python -m evals.run` from `latest.json` in this folder. Every number comes from the hand-labeled fictional set in `evals/data/holdout/`, read through the app's own pipeline. Each rate is shown with its counts, as (count/total).

## Run

| Setting | Value |
| --- | --- |
| Dataset | holdout (`evals/data/holdout`) |
| Pipeline version | 0.5.0-exact |
| Git commit | 6b763ac with uncommitted changes |
| Labels as of | 2026-11-01, passed to the app as today |
| Job parser | rules (Claude only with --llm) |
| Matching | exact |
| Matching by meaning (--semantic) | not requested |
| Claude parser and rewrites (--llm) | not requested |
| Libraries | Python 3.13.18, PyMuPDF 1.28.2, python-docx 1.2.0 |
| Labels | 6 resumes (18 roles, 9 education entries), 5 jobs (90 requirement lines), 8 pairs (110 requirement labels), no fact-check cases |

| Format | How the file is made |
| --- | --- |
| `pdf_inline` | PDF with the default PdfStyle: bullet glyph and text in one text run |
| `pdf_separate` | PDF with bullet_mode="separate": the glyph drawn on its own, as Word exports do |
| `docx` | DOCX from python-docx: Heading 1 sections and List Bullet paragraphs |

"Overall" pools the formats. The same resumes are read in each format, so it is not that many independent samples: a resume that fails in every format counts once per format.

## Headline numbers

| Metric | Result |
| --- | --- |
| Role detection recall (all formats) | 77.8% (42/54) |
| Total years within 0.5 of the label | 83.3% (15/18) |
| Requirement extraction recall | 97.8% (88/90) |
| Requirement extraction precision | 93.6% (88/94) |
| Priority accuracy on extracted requirements | 98.9% (87/88) |
| Pair status accuracy (all formats) | 64.5% (213/330) |
| False proven: app says direct, label says gap or needs_check | 2.0% (3/150) |
| Evidence recall@3 | 53.3% (96/180) |
| Fact checker accuracy, held-out set | n/a (0/0) |
| Fact checker false passes, held-out set | n/a (0/0) |

## Resume structure

A predicted role matches a labeled role when both its title and its employer match (equal after normalizing case and punctuation, or a fuzzy ratio of at least 0.85). Months are compared on matched roles. Total years counts as within 0.5 only when the app gives a number.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Role precision | 77.8% (14/18) | 77.8% (14/18) | 77.8% (14/18) | 77.8% (42/54) |
| Role recall | 77.8% (14/18) | 77.8% (14/18) | 77.8% (14/18) | 77.8% (42/54) |
| Start month correct (matched roles) | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 100.0% (42/42) |
| End month correct (matched roles) | 100.0% (14/14) | 100.0% (14/14) | 100.0% (14/14) | 100.0% (42/42) |
| Resumes with total years read | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 100.0% (18/18) |
| Total years within 0.5 | 83.3% (5/6) | 83.3% (5/6) | 83.3% (5/6) | 83.3% (15/18) |
| Total years mean absolute error (resumes with a value) | 0.43 | 0.43 | 0.43 | 0.43 |
| Education recall | 77.8% (7/9) | 77.8% (7/9) | 77.8% (7/9) | 77.8% (21/27) |
| Education precision | 77.8% (7/9) | 77.8% (7/9) | 77.8% (7/9) | 77.8% (21/27) |
| Education year correct (matched entries) | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) | 100.0% (21/21) |

Per resume, with one value per format (pdf_inline / pdf_separate / docx):

| Resume | Labeled roles | Roles matched | Labeled years | Years read |
| --- | --- | --- | --- | --- |
| h_r01_guidewire_claimcenter | 3 | 2 / 2 / 2 | 10.4 | 10.4 / 10.4 / 10.4 |
| h_r02_data_scientist | 3 | 2 / 2 / 2 | 10.3 | 10.3 / 10.3 / 10.3 |
| h_r03_salesforce_developer | 2 | 1 / 1 / 1 | 7.5 | 4.9 / 4.9 / 4.9 |
| h_r04_platform_cloud_engineer | 4 | 3 / 3 / 3 | 9.9 | 9.9 / 9.9 / 9.9 |
| h_r05_bi_developer | 3 | 3 / 3 / 3 | 12.4 | 12.4 / 12.4 / 12.4 |
| h_r06_mobile_developer | 3 | 3 / 3 / 3 | 7.4 | 7.4 / 7.4 / 7.4 |

## Requirement extraction

Extracted requirement texts are matched one to one with the labeled lines after normalizing case, whitespace and punctuation: equal, one containing the other, or a fuzzy ratio of at least 0.85. The job descriptions are plain text, so these numbers don't depend on the resume format.

| Metric | rules |
| --- | --- |
| Extraction precision (extracted items that are labeled lines) | 93.6% (88/94) |
| Extraction recall (labeled lines found) | 97.8% (88/90) |
| Priority accuracy on matched items | 98.9% (87/88) |
| Job minimum years correct | 100.0% (5/5) |
| Job title correct | 80.0% (4/5) |

Rule parser matches: 88 exact, 0 by containment, 0 fuzzy.

Per class, counting lines that weren't extracted against recall and extracted lines that aren't requirements against precision:

| Class | Precision | Recall |
| --- | --- | --- |
| required | 95.1% (39/41) | 95.1% (39/41) |
| preferred | 87.5% (28/32) | 100.0% (28/28) |
| context | 95.2% (20/21) | 95.2% (20/21) |

Confusion matrix for the rule parser (rows are labels, columns the parser's priority; not_a_requirement rows are extracted lines with no label):

| label \ app | required | preferred | context | not_extracted |
| --- | --- | --- | --- | --- |
| required | 39 | 0 | 0 | 2 |
| preferred | 0 | 28 | 0 | 0 |
| context | 1 | 0 | 20 | 0 |
| not_a_requirement | 1 | 4 | 1 | 0 |

Per job:

| Job | Labeled lines | Extracted | Matched | Priority correct | Min years (label / app) | Title correct |
| --- | --- | --- | --- | --- | --- | --- |
| h_j01_guidewire_claimcenter_developer | 18 | 21 | 18 | 18 | 7 / 7 | yes |
| h_j02_data_scientist | 16 | 16 | 16 | 16 | 4 / 4 | yes |
| h_j03_salesforce_developer | 19 | 17 | 17 | 16 | 5 / 5 | no |
| h_j04_platform_engineer | 20 | 22 | 20 | 20 | 6 / 6 | yes |
| h_j05_bi_developer | 17 | 18 | 17 | 17 | 5 / 5 | yes |

## Evidence and status per pair

Each labeled requirement in pairs.json is looked up in the app's report through the same text matching as above. The app's statuses map to the labels one to one, with not_assessed read as needs_check; a labeled requirement the parser didn't extract counts as not_extracted and is always wrong. Evidence recall looks at the first 1 or 3 lines the report cites (exact evidence skill by skill, then related evidence) and counts a hit when a line contains a labeled evidence string or is contained in one. It covers labeled direct, partial and adjacent items that have evidence strings. Years-only requirements cite no lines in the report, so recall is also shown without them.

| Metric | pdf_inline | pdf_separate | docx | overall |
| --- | --- | --- | --- | --- |
| Status accuracy | 64.5% (71/110) | 64.5% (71/110) | 64.5% (71/110) | 64.5% (213/330) |
| False proven (direct where the label is gap or needs_check) | 2.0% (1/50) | 2.0% (1/50) | 2.0% (1/50) | 2.0% (3/150) |
| Share of direct calls that are false proven | 2.6% (1/38) | 2.6% (1/38) | 2.6% (1/38) | 2.6% (3/114) |
| Direct where the label isn't direct | 6.2% (4/64) | 6.2% (4/64) | 6.2% (4/64) | 6.2% (12/192) |
| Gap precision | 86.2% (25/29) | 86.2% (25/29) | 86.2% (25/29) | 86.2% (75/87) |
| Gap recall | 59.5% (25/42) | 59.5% (25/42) | 59.5% (25/42) | 59.5% (75/126) |
| Labeled requirement not extracted | 1.8% (2/110) | 1.8% (2/110) | 1.8% (2/110) | 1.8% (6/330) |
| Evidence recall@1 | 45.0% (27/60) | 45.0% (27/60) | 45.0% (27/60) | 45.0% (81/180) |
| Evidence recall@3 | 53.3% (32/60) | 53.3% (32/60) | 53.3% (32/60) | 53.3% (96/180) |
| Evidence recall@1 without years-only items | 47.4% (27/57) | 47.4% (27/57) | 47.4% (27/57) | 47.4% (81/171) |
| Evidence recall@3 without years-only items | 56.1% (32/57) | 56.1% (32/57) | 56.1% (32/57) | 56.1% (96/171) |

Confusion matrix, all formats (rows are labels, columns the app):

| label \ app | direct | partial | adjacent | gap | needs_check | not_extracted |
| --- | --- | --- | --- | --- | --- | --- |
| direct | 102 | 9 | 0 | 0 | 21 | 6 |
| partial | 3 | 12 | 0 | 0 | 3 | 0 |
| adjacent | 6 | 3 | 0 | 12 | 3 | 0 |
| gap | 3 | 6 | 0 | 75 | 42 | 0 |
| needs_check | 0 | 0 | 0 | 0 | 24 | 0 |

Per status, all formats:

| Status | Precision | Recall |
| --- | --- | --- |
| direct | 89.5% (102/114) | 73.9% (102/138) |
| partial | 40.0% (12/30) | 66.7% (12/18) |
| adjacent | n/a (0/0) | 0.0% (0/24) |
| gap | 86.2% (75/87) | 59.5% (75/126) |
| needs_check | 25.8% (24/93) | 100.0% (24/24) |

Status accuracy by how well the resume fits the job (all formats):

| Fit | Status accuracy |
| --- | --- |
| strong | 67.5% (81/120) |
| mixed | 51.7% (45/87) |
| wrong | 70.7% (87/123) |

Correct statuses per pair, one value per format (pdf_inline / pdf_separate / docx):

| Pair | Fit | Labels | Correct |
| --- | --- | --- | --- |
| h_r01_guidewire_claimcenter x h_j01_guidewire_claimcenter_developer | strong | 13 | 11 / 11 / 11 |
| h_r06_mobile_developer x h_j01_guidewire_claimcenter_developer | wrong | 13 | 11 / 11 / 11 |
| h_r02_data_scientist x h_j02_data_scientist | strong | 13 | 8 / 8 / 8 |
| h_r01_guidewire_claimcenter x h_j02_data_scientist | wrong | 13 | 9 / 9 / 9 |
| h_r03_salesforce_developer x h_j03_salesforce_developer | strong | 14 | 8 / 8 / 8 |
| h_r04_platform_cloud_engineer x h_j04_platform_engineer | mixed | 15 | 7 / 7 / 7 |
| h_r03_salesforce_developer x h_j04_platform_engineer | wrong | 15 | 9 / 9 / 9 |
| h_r05_bi_developer x h_j05_bi_developer | mixed | 14 | 8 / 8 / 8 |

## Fact checker

This set has no fact-check labels (labels/factcheck.json and labels/factcheck_holdout.json), so the fact checker wasn't measured on it.

## Matching by meaning

Not run in this evaluation, because --semantic wasn't given. In exact mode the app never returns adjacent, so every item labeled adjacent counts as an error above. Install the ml extra (pip install -e ".[dev,ml]", with the CPU-only PyTorch first on Linux as the README shows), then run python -m evals.run --semantic. The first run downloads the two models from Hugging Face, about 180 MB.

## Claude parser and rewrites

Not run in this evaluation, because --llm wasn't given. No call was made to a model provider. Put ANTHROPIC_API_KEY in the environment or in a local .env file (see the README), then run python -m evals.run --llm. It makes one parse call per job and up to LLM_MAX_SUGGESTIONS rewrite candidates per pair (20 by default).

## Error analysis

Each pattern below is a rule over the default run's failures, and patterns are listed most frequent first. A count is of distinct labeled items: an item that fails in several formats counts once, and the formats are named. The text says what was observed in the extracted lines and reports, not a confirmed root cause.

### Requirements that name no catalog skill are left for a person to check

Pair status: 23 labeled requirements, all formats. The rule parser only finds skills from the skill catalog. A requirement whose tools or domain are outside it gets no skills, and a degree or certification requirement the app can't judge is left to a person, so exact matching marks it needs_check whether the resume proves it, lacks it or shows it in part.

- h_r01_guidewire_claimcenter x h_j01_guidewire_claimcenter_developer (all formats): "Knowledge of ISO ClaimSearch or other claims industry integrations": labeled direct; the parser found no catalog skill in it.
- h_r02_data_scientist x h_j02_data_scientist (all formats): "Experience with causal inference methods such as propensity scores, difference-in-diffe...": labeled direct; the parser found no catalog skill in it.
- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Salesforce Platform Developer II certification": labeled gap; the parser found no catalog skill in it.

### Related experience needs matching by meaning

Pair status: 8 labeled requirements, all formats. In exact mode the app never returns adjacent, so related experience the labels mark adjacent (GitLab CI for GitHub Actions, Java for C#) comes out as gap, partial or needs_check. Matching by meaning is meant for these and wasn't run.

- h_r06_mobile_developer x h_j01_guidewire_claimcenter_developer (all formats): "Experience with TeamCity or Jenkins build pipelines": labeled adjacent, app gap (Jenkins missing, CI/CD missing).
- h_r04_platform_cloud_engineer x h_j04_platform_engineer (all formats): "Deep, hands-on experience running Amazon EKS in production": labeled adjacent, app gap (Amazon EKS missing).
- h_r03_salesforce_developer x h_j04_platform_engineer (all formats): "Experience building CI/CD pipelines in GitHub Actions or CircleCI": labeled adjacent, app gap (CI/CD missing, GitHub Actions missing).

### Company and posting details are kept as requirements

Requirement extraction: 6 job lines. Company descriptions and posting lines are kept as requirements, usually as context: they name a skill or address the candidate, so the parser can't tell them from a duty.

- h_j01_guidewire_claimcenter_developer: "We are looking for a hands-on ClaimCenter developer to join the claims IT team." kept as required.
- h_j04_platform_engineer: "Mock Payments, Inc. | Remote, US (Eastern or Central time zones preferred)" kept as preferred.
- h_j05_bi_developer: "The team supports 14 hospitals and more than 200 clinics with reporting on quality, finance and operations." kept as context.

### Roles are found but the title or employer is split wrongly

Resume structure: 4 roles or entries, all formats. The role and its dates are read, but the title and employer are split in another place than the labels (extra text in one of them, or both in the title), so the role doesn't match its label.

- h_r02_data_scientist (all formats): role 'Graduate Research Assistant, Example State University': Read as a role with title 'Graduate Research Assistant' and employer 'Example State University, Department of Statistics'. Extracted line: "Graduate Research Assistant – Example State University, Department of Statistics | Aug 2016 – Jun 2020".
- h_r04_platform_cloud_engineer (all formats): role 'Adjunct Instructor, Sample Community College': Read as a role with title 'Adjunct Instructor, part-time' and employer 'Sample Community College'. Extracted line: "Sample Community College – Adjunct Instructor, part-time (01/2021 – 12/2021)".
- h_r05_bi_developer (all formats): education 'Master of Science, Information Systems': The degree or school was read differently. Extracted line: "Master of Science, Information Systems".

### A related skill or a missing detail is counted as direct proof

Pair status: 4 labeled requirements, all formats. The catalog files some tools under a broader skill as well (JUnit and NUnit also count as Unit testing, GitHub and GitLab as Git), so a requirement that names the broad skill can be proven by a line that names another tool, and a domain word ("payments") counts wherever a work line uses it.

- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Knowledge of PMD or other static code analysis tools for Apex": labeled partial, app direct from the experience line "Wrote Apex triggers on a trigger handler framework, plus batch and queueable Apex for n..." (Apex via 'Apex triggers').
- h_r04_platform_cloud_engineer x h_j04_platform_engineer (all formats): "Experience building CI/CD pipelines in GitHub Actions or CircleCI": labeled adjacent, app direct from the experience line "Azure, AKS, AWS (EC2, S3), Kubernetes, Docker, Terraform, Bicep, Helm, Kustomize, Flux,..." (CI/CD via 'GitLab CI').
- h_r05_bi_developer x h_j05_bi_developer (all formats): "Experience implementing row-level security in Power BI.": labeled adjacent, app direct from the experience line "Built Power BI reports with DAX measures for the HR and procurement teams, published to..." (Power BI via 'Power BI').

### Years requirements cite no resume lines

Evidence: 3 labeled requirements, all formats. For a years-only requirement the report gives the years it counted but no lines, while the labels cite the role header lines. These items always miss in evidence recall, which is why recall is also shown without them.

- h_r01_guidewire_claimcenter x h_j01_guidewire_claimcenter_developer (all formats): "7+ years of overall IT experience": labeled direct; the report cites no lines (10.4 years read).
- h_r06_mobile_developer x h_j01_guidewire_claimcenter_developer (all formats): "7+ years of overall IT experience": labeled direct; the report cites no lines (7.4 years read).
- h_r04_platform_cloud_engineer x h_j04_platform_engineer (all formats): "6+ years in infrastructure, DevOps, SRE or platform engineering roles": labeled direct; the report cites no lines (9.9 years read).

### The status is right but the first lines cited aren't the labeled ones

Evidence: 3 labeled requirements, all formats. The status matches the label, but none of the report's first three lines is a labeled evidence line. Evidence is listed skill by skill, so the first lines can all come from one skill of the requirement, or from a broad skill such as ETL (matched by "data pipelines").

- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Experience with Salesforce integrations using REST and SOAP APIs": labeled direct, app direct; first line: certifications line "Salesforce Certified Platform Developer I" (Salesforce via 'Salesforce').
- h_r05_bi_developer x h_j05_bi_developer (all formats): "At least 5 years of experience in business intelligence, data warehousing or reporting...": labeled direct, app direct; first line: experience line "Developed Informatica PowerCenter mappings that loaded the Oracle enterprise data wareh..." (Data warehousing via 'data warehouse').
- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Experience with Salesforce DevOps tools such as Copado, Gearset or Salesforce DX": labeled direct, app direct; first line: certifications line "Salesforce Certified Platform Developer I" (Salesforce via 'Salesforce').

### Labeled requirements are not extracted

Requirement extraction: 2 job lines. A labeled requirement line has no matching extracted requirement.

- h_j03_salesforce_developer: "Experience: 5 - 8 Years" (required) not found.
- h_j03_salesforce_developer: "Educational Qualification: B.E./B.Tech/MCA or equivalent" (required) not found.

### Work the labels count as shown is found only in a summary or skills line

Pair status: 2 labeled requirements, all formats. The labels count the work as shown in a bullet, but the bullet describes it in other words, so exact matching finds the skill only in the summary or skills section, or not at all, and calls the requirement partial.

- h_r02_data_scientist x h_j02_data_scientist (all formats): "4+ years of experience applying statistics or machine learning in industry": labeled direct, app partial (Statistics demonstrated, Machine learning listed).
- h_r05_bi_developer x h_j05_bi_developer (all formats): "Solid understanding of dimensional modeling (star schemas, slowly changing dimensions).": labeled direct, app partial (Data modeling listed).

### Labeled requirements missing from the report

Pair status: 2 labeled requirements, all formats. The job parser didn't extract the requirement, so the report has no status for it.

- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Experience: 5 - 8 Years": labeled direct; the parser didn't extract it.
- h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "Educational Qualification: B.E./B.Tech/MCA or equivalent": labeled direct; the parser didn't extract it.

Seen once:

- Roles not found in the extracted text. h_r01_guidewire_claimcenter (all formats): role 'Guidewire Developer, Demo Infotech Pvt. Ltd.': No extracted line holds both the title and the employer.
- Date ranges with a separator the parser doesn't accept are not read. h_r03_salesforce_developer (all formats): role 'Associate Salesforce Developer, Demo Technologies': No date range the app can read is on the line. Extracted line: "Associate Salesforce Developer | Demo Technologies, Chennai".
- Required lines get the wrong priority. h_j03_salesforce_developer: "Take part in requirement discussions with onsite teams and client stakeholders." labeled context, parsed as required.
- Years requirements fail when roles weren't read. h_r03_salesforce_developer x h_j03_salesforce_developer (all formats): "5+ years of hands-on Salesforce development experience": labeled direct, app partial with 4.9 years read in roles that mention Salesforce.

## Known weaknesses of this evaluation

- The sample is small: 6 resumes, 5 job descriptions, 8 pairs with 110 requirement labels, and 0 fact-check cases. One item moves a per-format pair rate by about half a point and a per-job rate by several points, and the three formats read the same resumes, so pooling them doesn't add independent evidence.
- The labels of the holdout set follow the conventions in evals/data/README.md. How far it differs from the development set in wording and layout decides how much this run says about real resumes.
- Matching by meaning and the Claude parser and rewrites are not run in CI, and were not run for this report unless the run table says so. Exact mode can't produce adjacent, and the Claude path is only exercised against a fake client in the tests.
- Every PDF comes from one builder (tests/builders.py). Since v0.5 it embeds the font file, so characters such as the en dash reach the app as written. Real exports from Word, Google Docs or LaTeX, two-column layouts, tables and text boxes are not covered.
- The evaluation's own matching rules (a fuzzy ratio of 0.85, containment for requirement texts, strict title and employer matching for roles) are choices. Other rules would move some role and requirement matches.

# Held-out evaluation data

This folder is a small held-out evaluation set for the resume evidence matcher. It holds 6 fictional resumes, 5 fictional job descriptions and gold labels for 8 resume and job pairings.

## How it was written

The set was written without access to the app or its results. While writing it, nobody opened, searched or ran anything under app/, tests/ (other than tests/builders.py, for the resume markup), evals/*.py or evals/results/, and the existing label files in evals/data/labels/ were not read. Only evals/data/README.md and three files from the main set (two resumes and one job) were read, to copy the file conventions. Every label was written by reading the text, not by running the app.

Use this set only to measure the app. Do not tune prompts, rules or thresholds against it. Once a change has been made because of a result on this set, it is no longer held out and a new one should be written.

## Status: no longer fully unseen

The v0.4 and v0.5 results on this set are blind: both versions were run on it once, after v0.5 was finished, and the label files were only reformatted to the standard field names (no label changed). After that, one resume and job pair from this set (h_r01 with h_j01) was used in a manual demo, which showed three reading mistakes: a "Pvt. Ltd." employer read as a job title, "W2" and "C2C" lines counted as requirements, and an intro sentence counted as a requirement. v1.0 fixed those three with general rules. Its numbers on this set are reported separately and are not blind. A new held-out set should be written before claiming further unseen-data results.

## Everything is fictional

Every person, employer, school, email address and phone number here is made up. Emails use example.com and phone numbers use (555) 010-0141 to (555) 010-0146. Company names follow the same patterns as the main set, such as "Sample Mutual Insurance Company", "Demo Savings Bank" and "Placeholder Lending Co.". Real technology names such as Guidewire, Salesforce, Power BI, Kubernetes and Databricks appear only as skills, products and certifications.

## Files and counts

| Path | What it holds | Count |
| --- | --- | --- |
| resumes/*.md | Resumes in the markup read by tests/builders.py | 6 |
| jobs/*.txt | Job descriptions as plain text | 5 |
| labels/jobs.json | Title, minimum years and every requirement line per job | 90 requirements: 41 required, 28 preferred, 21 context |
| labels/resumes.json | Roles, dates, total years and education per resume | 6 resumes, 18 roles, 9 education entries |
| labels/pairs.json | Resume and job pairings with a status for every required and preferred requirement | 8 pairs, 110 requirement labels |

Pair labels by status: 46 direct, 6 partial, 8 adjacent, 42 gap and 8 needs_check. By fit: 3 strong, 2 mixed and 3 wrong. Each resume is used in one or two pairs. There is no mobile job, so the mobile resume appears only in a wrong pairing. This set has no fact check cases.

## Pairs

| Resume | Job | Fit |
| --- | --- | --- |
| h_r01_guidewire_claimcenter | h_j01_guidewire_claimcenter_developer | strong |
| h_r06_mobile_developer | h_j01_guidewire_claimcenter_developer | wrong |
| h_r02_data_scientist | h_j02_data_scientist | strong |
| h_r01_guidewire_claimcenter | h_j02_data_scientist | wrong |
| h_r03_salesforce_developer | h_j03_salesforce_developer | strong |
| h_r04_platform_cloud_engineer | h_j04_platform_engineer | mixed |
| h_r03_salesforce_developer | h_j04_platform_engineer | wrong |
| h_r05_bi_developer | h_j05_bi_developer | mixed |

The two mixed pairs are near misses that a recruiter would still screen. The platform engineer works on Azure and the job is built on AWS, so several required items are adjacent. The BI developer works mainly in Tableau and Informatica and the job is built on Power BI and SSIS.

## What each resume tests

| Resume | Role line format | Other features | Total years |
| --- | --- | --- | --- |
| h_r01_guidewire_claimcenter | Employer, city and state on the bold line, then "Title \| Jun 2021 - Till Date" on the next line | Upper case headings, summary as bullets, skills with aligned colons, "Client:" line, "Environment:" line under each role | 10.4 |
| h_r02_data_scientist | "Title - Employer, City, ST \| Mar 2023 - Present" on one line | "Tech stack:" line under each role, a research assistant role, education as plain lines with one degree and no year, publications section | 10.3 |
| h_r03_salesforce_developer | "Title \| Employer, City" on the bold line, dates on the next line | Dates written as "Jun'19 - Dec'21", certifications before experience, skills as labeled bullets, education as a year range | 7.5 |
| h_r04_platform_cloud_engineer | "Employer - Title (09/2022 - Current)" | Part-time role inside a full-time role, a gap from July 2018 to January 2019, one comma skills line under "Core Tools" | 9.9 |
| h_r05_bi_developer | "Title, Employer" on the bold line, then "City, ST \| April 2021 - Present" | A year-only role ("2017 - 2021") that overlaps the next role by nine months, a gap for a master's degree, pipe separated skills under "Areas of Expertise", bullet glyphs in the contact line | 12.4 |
| h_r06_mobile_developer | "Title @ Employer \| May 2022 - Present" with a plain hyphen | Internship, a one month gap, side projects section, skills lines that use an en dash as a separator, education over three plain lines | 7.4 |

In the files, the dashes in role lines and date ranges are en dashes (U+2013) in every resume except h_r06_mobile_developer, which uses plain hyphens there. This README writes them all as hyphens.

## What each job tests

| Job | Format features |
| --- | --- |
| h_j01_guidewire_claimcenter_developer | Staffing agency posting with "Client:", "Duration:" and "Rate:" lines, headings ending with a colon, numbered must have list, "7+ years" and "4+ years of" a named product, W2 and visa text |
| h_j02_data_scientist | Headings without colons, duties written as three prose sentences, degree requirement with alternatives, salary sentence, no visa sponsorship |
| h_j03_salesforce_developer | Indian posting with "Experience: 5 - 8 Years", CTC in LPA and a notice period line, U+2022 bullet glyphs, certification requirements, degree line after the lists |
| h_j04_platform_engineer | "*" bullets, headings ending with a colon, "Extra credit" heading, many "X or Y" alternatives, compensation line with equity, visa sponsorship offered |
| h_j05_bi_developer | No bullets at all, qualifications as plain lines ending with a period, duties as prose sentences, requisition number, degree or experience alternative, pay range |

Lines such as "Location:", "Duration:", "Rate:", "CTC:" and "Notice Period:" are hiring logistics, not qualifications, and are not labeled. "Experience: 5 - 8 Years" in h_j03 is labeled as a required years requirement.

## Label file formats

The field names below were chosen from the descriptions in evals/data/README.md, because the main label files were deliberately not opened. If they differ from the files in evals/data/labels, rename the fields when loading. The meanings are the same.

- labels/jobs.json is an object keyed by job id (the file name without ".txt"). Each value has "title", "min_years" (a number) and "requirements", a list of objects with "text" and "priority" in file order.
- labels/resumes.json is an object keyed by resume id (the file name without ".md"). Each value has "name", "as_of" ("2026-11-01"), "roles", "total_years" and "education". Each role has "title", "employer", "start" and "end", where dates are "YYYY-MM" and "end" is null for a current role. Each education entry has "degree", "school" and "year", where "year" is null when the resume gives none.
- labels/pairs.json is a list of pairs. Each pair has "resume", "job", "fit" ("strong", "mixed" or "wrong") and "labels". Each label has "text" (the exact requirement text from jobs.json), "priority", "status" and "evidence", a list of strings.

## Label definitions

These are the same as in evals/data/README.md.

### Requirement priority (jobs.json)

- required: a must-have qualification.
- preferred: a nice-to-have qualification.
- context: a responsibility or duty of the job.

Company intros, benefits, salary, EEO statements, visa text and how to apply text are never labeled. Each requirement "text" is the exact line from the job file without its bullet glyph or number. In prose paragraphs each sentence that states a requirement or duty is its own item, copied exactly.

### Pair status (pairs.json)

- direct: clearly shown in work experience or projects. A bullet or role line names it or plainly demonstrates it.
- partial: only listed in the skills section or summary, or only some of several named skills are shown.
- adjacent: the exact skill is absent, but closely related real experience exists.
- gap: nothing relevant in the resume.
- needs_check: cannot be judged from the resume text.

Every evidence string is an exact substring of one line of the named resume file, with the markup prefix ("- ", "### ") left out. Evidence is empty for gap and needs_check and never empty for the other statuses. Only required and preferred requirements are labeled in pairs; context items are not.

## Dates and years

All resumes are labeled as of 2026-11-01. Month counting is inclusive: a role from 2022-03 to the present counts every month from March 2022 through November 2026, which is 57 months. A date given as a year only counts from January of the start year to December of the end year. Overlapping months are counted once and gaps add nothing. Total years is the merged month count divided by 12, rounded to one decimal.

## Labeling conventions

All conventions from evals/data/README.md apply. In short:

- Years requirements worded broadly are decided from the hand-computed total years: direct if met, gap if not. For years requirements, the evidence is the role lines and date lines that count.
- Skill-with-years lines use the months in roles that show that skill. "6+ years in infrastructure, DevOps, SRE or platform engineering roles" is a gap for the Salesforce resume, since none of its roles are infrastructure roles.
- A range like "5 - 8 Years" is read as a minimum of 5.
- Internships and part-time roles count toward total years.
- A tool named on an "Environment:" line under a role is direct. A tool named only in a skills, tools or summary section is partial.
- Certification lines are direct evidence for certification requirements, and education lines are direct evidence for degree requirements.
- A requirement with alternatives is direct when any one alternative is shown directly.
- Words like "strong", "expert" or "deep" do not change the status.
- Every soft-skill line is needs_check, even when a bullet hints at the skill.

These calls were made in this set and are written down so they can be reviewed:

- A "Tech stack:" line under a role is treated the same as an "Environment:" line, so a tool named there is direct.
- "4+ years of experience applying statistics or machine learning in industry" counts only the industry roles for the data scientist (6.4 years) and leaves out the graduate research assistant role. The status is direct either way.
- A lower level of the asked-for certification is a gap. Platform Developer I does not count toward a Platform Developer II requirement.
- When a line names two skills joined by "and" and only one is shown, the label is partial. DAX is shown in a Power BI bullet but Power Query is not, so "Advanced DAX and Power Query skills" is partial.
- Azure work stands in as adjacent for AWS requirements: AKS for Amazon EKS, Azure networking and Entra ID roles for AWS networking and IAM, and Azure DevOps pipelines for GitHub Actions. Informatica PowerCenter is adjacent for SSIS, Tableau user filters are adjacent for Power BI row-level security, Bitrise for TeamCity or Jenkins, and Copado pipelines for GitHub Actions or CircleCI.
- Building an internal developer platform with service scaffolding tools is adjacent for "Backstage or another internal developer portal", since no portal is named.
- A REST integration to a vendor appraisal service and a fraud scoring API counts as direct for "ISO ClaimSearch or other claims industry integrations".
- A mobile developer who defined REST APIs with a backend team is direct for "Experience with SOAP or REST web service integrations". Wrong pairs can still have direct items, such as total years and SQL.
- "NLP basics" in a skills line is partial for "Experience with NLP on clinical notes using spaCy or Hugging Face Transformers".

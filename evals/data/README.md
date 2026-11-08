# Evaluation data

This folder is a hand-labeled evaluation set for the resume evidence matcher. It holds fictional resumes, fictional job descriptions and gold labels. Every label was written by a person reading the text. None of it was produced or checked by running the app, so the set can be used to measure the app without being circular.

## Everything is fictional

Every person, employer, school, email address and phone number here is made up. Emails use example.com and phone numbers use (555) 010-01xx. Company names follow patterns like "Example Mutual", "Sample Retail Group", "Placeholder Bank" and "Demo Logistics". Real technology names such as AWS, Azure, Snowflake, Kubernetes and Guidewire appear only as skills and products.

## Files and counts

| Path | What it holds | Count |
| --- | --- | --- |
| resumes/*.md | Resumes in the markup read by tests/builders.py | 12 |
| jobs/*.txt | Job descriptions as plain text | 8 |
| labels/jobs.json | Title, minimum years and every requirement line per job | 121 requirements: 56 required, 32 preferred, 33 context |
| labels/resumes.json | Roles, dates, total years and education per resume | 12 resumes, 35 roles, 15 education entries |
| labels/pairs.json | Resume and job pairings with a status for every required and preferred requirement | 16 pairs, 176 requirement labels |
| labels/factcheck.json | Original bullet, rewritten bullet and whether the rewrite adds a fact | 60 cases |

Pair labels by status: 98 direct, 11 partial, 9 adjacent, 49 gap, 9 needs_check. Each pair also has a "fit" field: 9 strong, 4 mixed and 3 wrong (a pairing no recruiter would make, such as the QA resume against the ML job). Each resume is used in one or two pairs.

Fact check cases: 30 adds_fact and 30 faithful. By category: 5 added_number, 6 changed_number, 5 added_tool, 3 added_employer, 3 added_date, 3 added_certification, 5 added_scope, 6 faithful_reword, 5 faithful_trim, 5 faithful_reorder and 14 tricky_faithful.

## What each resume tests

| Resume | Role line format | Other features |
| --- | --- | --- |
| r01_data_engineer | "Title, Employer \| Mar 2022 - Present" | Skills as "Languages: Python, SQL" lines |
| r02_dotnet_fullstack | "Employer - Title (2019 - 2021)" with years only | Skills as one comma line |
| r03_react_frontend | "Title at Employer, Jun 2019 – Feb 2022" with an en dash | Internship counted as a role |
| r04_ml_engineer | "Title - Employer - Aug 2021 to Present" | Part-time role overlapping a full-time role, two degrees |
| r05_devops_sre | Role line, then a separate line with only the dates | "Current" instead of Present, certifications section |
| r06_qa_automation | "Title \| Employer \| 03/2020 - 01/2023" | "Current", skills under a "Tools" heading, degree and school on separate lines |
| r07_data_analyst | "Title, Employer \| Aug 2022 - Present" | Career gap from April 2020 to July 2022, no skills section |
| r08_guidewire_developer | "Title, Employer, City, ST \| Apr 2022 - Till date" | "Environment:" line under each role, summary written as bullets |
| r09_java_backend | "Employer: Title, May 2021 - present" | No summary, skills written as bullets, middle dots in the contact line |
| r10_python_backend | "Title, Employer \| Feb 2023 - Present" | No section headings at all, unlabeled skills line, education as a plain line |
| r11_cloud_data_architect | "Title, Employer (Oct 2022 - Present)" | Long resume: 4 roles with 5 to 7 bullets each |
| r12_junior_developer | "Title - Employer (May 2024 - Aug 2024)" | Entry level, education first, projects section, internship |

## What each job tests

| Job | Format features |
| --- | --- |
| j01_senior_data_engineer | Responsibilities, Requirements and Nice to have headings, About Us block, salary and benefits list, EEO statement, how to apply line, "5+ years" |
| j02_dotnet_fullstack_developer | "Job Title:" and other prefix lines, Must have and Good to have headings, "3-5 years", soft-skill line |
| j03_frontend_react_engineer | Prose paragraphs with no bullets, salary sentence, EEO sentence |
| j04_ml_engineer | Numbered lists, headings ending with a colon, "Minimum 4 yrs", a numbered benefits list that is not a requirement |
| j05_site_reliability_engineer | "*" bullets, headings ending with a colon, many "X or Y" alternatives, soft-skill line, compensation line |
| j06_qa_automation_engineer | "•" bullets, "Who we are" block, perks list |
| j07_backend_java_developer | "Position:" prefix lines, duties written as prose, "4+ years with Java", About Us at the end |
| j08_guidewire_policycenter_developer | "Job Title:" and "Client:" lines, "Mandatory Skills:" and "Desired Skills:" headings, closing boilerplate paragraph |

## Label definitions

### Requirement priority (jobs.json)

- required: a must-have qualification.
- preferred: a nice-to-have qualification.
- context: a responsibility or duty of the job.

Company intros, benefits, salary, EEO statements and how to apply text are never labeled. Each requirement "text" is the exact line from the job file without its bullet glyph or number. In prose paragraphs each sentence that states a requirement or duty is its own item, copied exactly.

### Pair status (pairs.json)

- direct: clearly shown in work experience or projects. A bullet or role line names it or plainly demonstrates it.
- partial: only listed in the skills section or summary, or only some of several named skills are shown.
- adjacent: the exact skill is absent, but closely related real experience exists. Examples: GitLab CI for a GitHub Actions requirement, AWS ECS for a Kubernetes requirement.
- gap: nothing relevant in the resume.
- needs_check: cannot be judged from the resume text, such as "Strong attention to detail".

Every evidence string is an exact substring of one line of the named resume file. Evidence is empty for gap and needs_check. Only required and preferred requirements are labeled in pairs; context items are not.

### Fact check labels (factcheck.json)

- faithful: the rewrite says nothing the source does not say. Dropping facts is allowed.
- adds_fact: the rewrite adds or changes a fact. The "added" list names each added fact as it appears in the rewrite.

Tricky faithful cases write the same fact differently, for example "40+" and "40 or more", "5 hours to 90 minutes" and "from five hours to 90 minutes", or "CI/CD" and "continuous integration and delivery". Tricky violations include a single changed digit, a vague claim made specific ("a team" to "a team of 8 engineers") and "improving" turned into "doubling".

## Dates and years

All resumes are labeled as of 2026-11-01. Month counting is inclusive: a role from 2022-03 to the present counts every month from March 2022 through November 2026, which is 57 months. A date given as a year only counts from January of the start year to December of the end year. Overlapping months are counted once and gaps add nothing. Total years is the merged month count divided by 12, rounded to one decimal.

## Labeling conventions

These are the judgment calls made while labeling. Change them here first if the team decides otherwise.

- Years requirements are decided from the hand-computed total years: direct if met, gap if not. The job lines are worded broadly (for example "software or data engineering experience") so that the total is a fair measure.
- Skill-with-years lines, such as "4+ years with Java" or "Minimum 3 years of hands-on Guidewire PolicyCenter or BillingCenter configuration", use the months in roles that show that skill.
- A range like "3-5 years" is read as a minimum of 3. More experience is still direct.
- Internships and part-time roles count toward total years.
- An "Environment:" line under a role counts as work experience, so a tool named there is direct. A tool named only in a skills, tools or summary section is partial.
- Certification lines are direct evidence for certification requirements, and education lines are direct evidence for degree requirements.
- A requirement with alternatives ("Kafka or Kinesis") is direct when any one alternative is shown directly.
- A version requirement with no version on the resume ("Angular 12 or later" against an Angular bullet with no version) is partial.
- Words like "strong" or "solid" do not change the status. The status describes the evidence, not its depth.
- Every soft-skill line is needs_check in this set.

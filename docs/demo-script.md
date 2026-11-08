# Demo video script

A 4 to 5 minute screen recording of version 1.0, using only the fictional samples in `samples/`. Nothing in it is a real person's resume.

## Before recording

1. Start the stack with `docker compose up --build` and wait until http://localhost:8501 shows the login screen (ClamAV takes a minute or two on its first start). For the rewrite part, set `ANTHROPIC_API_KEY` in your local `.env` before starting. Without a key, skip the part marked optional.
2. Have these ready to drag in or open:
   - `samples/generated/jordan_example_data_engineer.pdf` (the resume)
   - `samples/jobs/data_engineer.txt` (the job description, open in a text editor so you can copy it)
3. Use a demo account that doesn't exist yet, such as `demo@example.com`, and a password of 12 or more characters you can type on camera.
4. Optional, for the scanning part: the EICAR test file from https://www.eicar.org (a harmless file every virus scanner flags on purpose), saved as `eicar-test.pdf`. Some antivirus tools on your own machine will remove it as soon as it is saved, so prepare it in a folder they skip or leave this part out.
5. Make the browser window about 1280 by 800 and zoom to 110% so the text reads well in the video.

## Script

| Time | What to click | What to say |
| --- | --- | --- |
| 0:00 to 0:20 | The login screen. | "This is the resume evidence matcher. You give it your resume and a job description, and for every requirement it shows which of your lines prove it, which requirements nothing proves, and what to do next. It never adds skills or numbers you don't have, and it doesn't give you a made-up match score." |
| 0:20 to 0:45 | Create account tab. Type the email and the password twice. Click Create account. | "Version 1.0 has accounts. Passwords need 12 characters and are stored only as argon2id hashes. There's no email yet, so there's no verification link: that's on the roadmap. Each person sees only their own analyses." |
| 0:45 to 1:10 | Drag in the PDF. Paste the job description. Click Check my resume. | "This is a fictional data engineer resume and a fictional job. Before the file is read, ClamAV scans it for malware. The file itself is never stored; only the report and the lines the app read are kept, for 24 hours." |
| 1:10 to 1:40 | Point at the Coverage table, then scroll to the Required cards. | "Five of the six required items are proven by work experience, with the exact line and page. 5+ years is checked against the role dates: about seven and a half years. Git and CI/CD only appear in the skills list, so the app says to add a bullet that shows where you used them, if you did." |
| 1:40 to 2:05 | Scroll to Preferred. Open the dbt card. | "dbt isn't in the resume, so it's marked missing, and the next step is to leave it out unless it's true. Instead of writing it in for you, the app asks a question." |
| 2:05 to 2:30 | In the dbt card, type "No, only a tutorial." in the answer box. Click Save answer. | "My answer is saved with this analysis and never put into the resume. It's there to help me decide what to say in an interview." |
| 2:30 to 3:05 | Optional, with a Claude key: on "Strong Python and SQL", click Suggest rewrites. Accept one suggestion. | "With a Claude key, the app can suggest clearer wording for a line that proves a requirement. Every suggestion goes through a fact checker first, and any rewrite that adds a number, a date, a tool or a bigger claim is thrown away. The note here says how many were discarded." |
| 3:05 to 3:35 | Open "Fix text the app read wrongly". Change one line slightly. Click Save corrections. Scroll to Your changes. | "If the app read a line wrongly, I can fix it. Corrections and accepted rewrites are listed separately, so I can see exactly what changed." |
| 3:35 to 3:50 | Click Download Word file and open it. | "The export is a plain single-column Word file with my lines in their original order and my changes applied." |
| 3:50 to 4:10 | Optional: upload `eicar-test.pdf` with the same job description. | "Here's the standard antivirus test file. The scanner flags it, the upload is refused, and nothing is stored. If the scanner were down, uploads would stop rather than go through unscanned." |
| 4:10 to 4:35 | Sidebar: Delete my account and data. Read the warning. Click Yes, delete everything. | "When I'm done, I can delete my account. It asks once more, then removes the account, its analyses, suggestions, corrections and answers at once, not after 24 hours." |
| 4:35 to 4:50 | Log in tab: try the same email and password. The error appears. | "The account is gone, so the login fails. The error is the same one you'd get for a wrong password, so it doesn't tell anyone which emails have accounts." |
| 4:50 to 5:00 | Switch to http://localhost:8000/docs. | "Everything here is also an API, documented at /docs. The README has the evaluation results and the steps to deploy it on Azure." |

## Notes

- Keep the recording under 5 minutes by skipping the optional rows; without them it runs about 3 minutes 45 seconds.
- Don't show a terminal with your `.env` file or any key. The key never appears on the screen itself.
- The numbers said above come from the sample pair with exact matching and the rule parser, which is what `docker compose up --build` runs. With `INSTALL_ML=true`, the "Mentor two junior engineers" duty may show as related evidence to confirm.

# AI Job Search Automation Agent

Build a Python system that:

1. Reads CV.pdf
2. Extracts skills using an LLM
3. Searches job websites
4. Evaluates job descriptions using LLM
5. Scores jobs (1–10)
6. Classifies jobs:
   - research
   - industry
7. Groups jobs by country
8. Generates HTML report
9. Sends Gmail email
10. Runs daily via GitHub Actions

Required modules:

src/parse_cv.py
src/job_search.py
src/evaluate_jobs.py
src/rank_jobs.py
src/report_builder.py
src/email_sender.py

Outputs:

data/profile.json
data/jobs_raw.json
data/jobs_scored.json
output/report.html

Dependencies:

openai
pdfplumber
requests
beautifulsoup4
pandas

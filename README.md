# CV-automation

An automated job search pipeline that reads your CV, finds relevant job listings, scores each one against your profile using an LLM, and emails you a ranked HTML report — every day, hands-free.

---

## How it works

The pipeline runs six steps in sequence:

| Step | Module | What it does | Output |
|------|--------|--------------|--------|
| 1 | `parse_cv` | Extracts your skills and profile from `CV.pdf` via GPT-4o-mini | `data/profile.json` |
| 2 | `job_search` | Searches Remotive.io and Hacker News *Who is Hiring?* using your skills as keywords | `data/jobs_raw.json` |
| 3 | `evaluate_jobs` | Scores each job 1–10 and classifies it as *research* or *industry* using GPT-4o-mini | `data/jobs_scored.json` |
| 4 | `rank_jobs` | Sorts jobs by score, groups them by country and classification | *(in-memory)* |
| 5 | `report_builder` | Builds a styled HTML report grouped by country → classification | `output/report.html` |
| 6 | `email_sender` | Sends the HTML report to your inbox via Gmail SMTP | email |

---

## Prerequisites

- **Python 3.11+**
- An **OpenAI API key** (GPT-4o-mini access)
- A **Gmail account** with an [App Password](https://support.google.com/accounts/answer/185833) enabled

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/JinghaoW/CV-automation.git
cd CV-automation

# 2. (Recommended) Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Configuration

All configuration is provided through **environment variables**. Export them in your shell or add them to a `.env` file (not committed to git).

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key |
| `GMAIL_SENDER` | ✅ | Gmail address used to send the report (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASS` | ✅ | 16-character Gmail App Password (enter without spaces) |
| `GMAIL_RECIPIENT` | ✅ | Email address that receives the report |
| `CV_PATH` | ❌ | Path to your CV PDF (default: `CV.pdf` in the project root) |
| `EMAIL_SUBJECT` | ❌ | Custom subject line (default: `Daily Job Search Report`) |

**Example (Linux / macOS):**

```bash
export OPENAI_API_KEY="sk-..."
export GMAIL_SENDER="you@gmail.com"
export GMAIL_APP_PASS="abcdefghijklmnop"
export GMAIL_RECIPIENT="inbox@example.com"
export CV_PATH="CV.pdf"
```

---

## Usage

### 1. Add your CV

Place your CV as a PDF in the project root and set `CV_PATH` accordingly (default filename: `CV.pdf`).

### 2. Run the full pipeline

```bash
python main.py
```

The pipeline prints progress for each step and exits with a non-zero code if any critical step fails. A failed email send is treated as a warning — the report is still written to `output/report.html`.

### 3. Run individual modules

Each module can also be run standalone for testing or debugging:

```bash
python -m src.parse_cv        # Step 1 – parse CV → data/profile.json
python -m src.job_search      # Step 2 – search jobs → data/jobs_raw.json
python -m src.evaluate_jobs   # Step 3 – score jobs → data/jobs_scored.json
python -m src.rank_jobs       # Step 4 – rank jobs (prints JSON to stdout)
python -m src.report_builder  # Step 5 – build report → output/report.html
python -m src.email_sender    # Step 6 – send email
```

---

## Output

| File | Description |
|------|-------------|
| `data/profile.json` | Extracted candidate profile (name, skills, experience, education, languages, summary) |
| `data/jobs_raw.json` | Raw job listings fetched from job sources |
| `data/jobs_scored.json` | Jobs enriched with LLM score (1–10), classification, and reasoning |
| `output/report.html` | Styled HTML report grouped by country and job type |

Open `output/report.html` in any browser to view the report locally.

---

## Automated daily runs (GitHub Actions)

The workflow in `.github/workflows/daily_job_search.yml` runs the pipeline automatically **every day at 07:00 UTC**.

### Setup

1. Fork or push this repository to your GitHub account.
2. Go to **Settings → Secrets and variables → Actions** and add the following repository secrets:

   | Secret name | Value |
   |-------------|-------|
   | `OPENAI_API_KEY` | Your OpenAI API key |
   | `GMAIL_SENDER` | Sender Gmail address |
   | `GMAIL_APP_PASS` | Gmail App Password |
   | `GMAIL_RECIPIENT` | Recipient email address |

3. Commit your `CV.pdf` to the repository root (or adjust the `CV_PATH` env var in the workflow file).

The workflow also supports **manual triggers**: go to **Actions → Daily Job Search → Run workflow**.

After each run, `output/report.html` and `data/jobs_scored.json` are uploaded as workflow artifacts and can be downloaded from the Actions run page.

---

## Project structure

```
CV-automation/
├── main.py                        # Pipeline orchestrator
├── requirements.txt               # Python dependencies
├── CV.pdf                         # Your CV (add this yourself, not committed)
├── data/
│   ├── profile.json               # Generated: candidate profile
│   ├── jobs_raw.json              # Generated: raw job listings
│   └── jobs_scored.json           # Generated: scored job listings
├── output/
│   └── report.html                # Generated: HTML report
├── src/
│   ├── parse_cv.py                # Step 1 – CV parsing
│   ├── job_search.py              # Step 2 – job searching (Remotive, HN)
│   ├── evaluate_jobs.py           # Step 3 – LLM job evaluation
│   ├── rank_jobs.py               # Step 4 – ranking & classification
│   ├── report_builder.py          # Step 5 – HTML report generation
│   └── email_sender.py            # Step 6 – Gmail delivery
└── .github/
    └── workflows/
        └── daily_job_search.yml   # Scheduled GitHub Actions workflow
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `openai` | GPT-4o-mini API calls for CV parsing and job evaluation |
| `pdfplumber` | Extract text from CV PDF |
| `requests` | HTTP requests to job search APIs |
| `beautifulsoup4` | Parse HTML job descriptions |
| `pandas` | Rank and group job data |

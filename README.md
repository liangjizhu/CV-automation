# CV-automation

An automated job search pipeline that reads your CV, finds relevant job listings, scores each one against your profile using an LLM, and emails you a ranked HTML report — every day, hands-free.

---

## How it works

The pipeline runs six steps in sequence:

| Step | Module | What it does | Output |
|------|--------|--------------|--------|
| 1 | `parse_cv` | Extracts your skills and profile from `CV.pdf` via the configured LLM (DeepSeek by default; any OpenAI-compatible endpoint works) | `data/profile.json` |
| 2 | `job_search` | Searches Remotive.io, Hacker News *Who is Hiring?*, Arbeitnow, RemoteOK and Jobicy using your skills as keywords; tags every result with an inferred country/region | `data/jobs_raw.json` |
| 3 | `evaluate_jobs` | Scores each job 1–10 and classifies it as *research* or *industry* using the configured LLM | `data/jobs_scored.json` |
| 4 | `rank_jobs` | Sorts jobs by score, groups them by country and classification | *(in-memory)* |
| 5 | `report_builder` | Builds a styled HTML report grouped by country → classification | `output/report.html` |
| 6 | `email_sender` | Sends the HTML report to your inbox via Gmail SMTP | email |

---

## Prerequisites

- **Python 3.11+**
- An **LLM API key** for any OpenAI-compatible provider — by default the
  pipeline talks to **DeepSeek** (`deepseek-chat`), but you can switch to
  OpenAI, Groq, Together, Ollama, … by setting `LLM_BASE_URL` / `LLM_MODEL`.
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

All settings live in **`config.py`** at the project root. Open it and fill in
your values — every setting has an inline comment explaining what it does.

```python
# config.py (excerpt)

CV_PATH        = os.environ.get("CV_PATH", "cv/CV.pdf")          # path to your CV
LLM_API_KEY    = os.environ.get("LLM_API_KEY",
                                os.environ.get("OPENAI_API_KEY", ""))  # LLM key (DeepSeek/OpenAI/…)
LLM_BASE_URL   = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL      = os.environ.get("LLM_MODEL",    "deepseek-chat")
GMAIL_SENDER   = os.environ.get("GMAIL_SENDER",   "")            # sender Gmail
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")            # Gmail App Password
GMAIL_RECIPIENT= os.environ.get("GMAIL_RECIPIENT","")            # recipient email
EMAIL_SUBJECT  = os.environ.get("EMAIL_SUBJECT",  "Daily Job Search Report")
COUNTRY        = os.environ.get("COUNTRY",        "")            # optional country/region filter
```

### Job sources

The `job_search` step queries five public, no-auth APIs in parallel and
deduplicates the results by URL. None of them require an account or a key.

| Source | Endpoint | Notes |
|--------|----------|-------|
| Remotive.io | `https://remotive.com/api/remote-jobs` | Server-side keyword search |
| Hacker News *Who is hiring?* | `https://hn.algolia.com/api/v1/search` | Comments are parsed for a `Location:` line so each HN job ships with a real country |
| Arbeitnow.com | `https://www.arbeitnow.com/api/job-board-api` | EU-heavy; client-side keyword filter |
| RemoteOK | `https://remoteok.com/api` | Global remote board; the metadata banner element is skipped |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs` | Queried once per top-3 skill via the `tag` parameter |

A failure in any single source is logged and the pipeline keeps going with
whatever the other sources returned.

### Choosing an LLM provider

The pipeline uses the OpenAI Python SDK against any OpenAI-compatible endpoint.
Pick the row that matches your provider:

| Provider | `LLM_BASE_URL` | `LLM_MODEL` |
|----------|----------------|-------------|
| **DeepSeek** *(default)* | `https://api.deepseek.com/v1` | `deepseek-chat` |
| OpenAI                   | *(blank)*                     | `gpt-4o-mini` |
| Groq                     | `https://api.groq.com/openai/v1` | `llama-3.1-70b-versatile` |
| Together                 | `https://api.together.xyz/v1` | `meta-llama/Llama-3.1-70B-Instruct-Turbo` |
| Ollama (local)           | `http://localhost:11434/v1`   | `llama3.1` |

You can configure the pipeline in two ways:

| Method | When to use |
|--------|-------------|
| Edit `config.py` directly | Local development |
| Export environment variables | CI / GitHub Actions |

Environment variables always take precedence over values written in `config.py`.

| Variable / `config.py` key | Required | Description |
|----------------------------|----------|-------------|
| `LLM_API_KEY` | ✅ | API key for your LLM provider (DeepSeek by default). `OPENAI_API_KEY` is honoured as a fallback for backward compatibility. |
| `LLM_BASE_URL` | ❌ | Provider's OpenAI-compatible endpoint (default: `https://api.deepseek.com/v1`). Leave blank to talk to OpenAI. |
| `LLM_MODEL` | ❌ | Chat-completions model name (default: `deepseek-chat`). |
| `GMAIL_SENDER` | ✅ | Gmail address used to send the report (e.g. `you@gmail.com`) |
| `GMAIL_APP_PASS` | ✅ | 16-character Gmail App Password (enter without spaces) |
| `GMAIL_RECIPIENT` | ✅ | Email address that receives the report |
| `CV_PATH` | ❌ | Path to your CV PDF (default: `cv/CV.pdf`; uses `os.path.join` internally for cross-platform compatibility) |
| `EMAIL_SUBJECT` | ❌ | Custom subject line (default: `Daily Job Search Report`) |
| `COUNTRY` | ❌ | Filter jobs by country or region. Supports a single value (`"United States"`) **or a comma-separated OR list** (`"United States, Germany, Remote"`). Each term is matched case-insensitively against the inferred country *and* the raw location string, so values like `"Berlin"`, `"EMEA"`, or `"Worldwide"` also work. Leave blank to include all locations (default: `""`). |

---

## Usage

### 1. Add your CV

Place your CV PDF inside the **`cv/`** folder (the default expected filename is `CV.pdf`).
If you use a different filename, update `CV_PATH` in `config.py` accordingly.

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

## Testing

Unit tests live in the `tests/` directory and can be run with:

```bash
pytest tests/ -v
```

The tests cover all six modules and do **not** require an OpenAI API key, a Gmail account, or a CV PDF — external services are replaced with lightweight mocks. 58 tests are included covering:

| Test file | What is tested |
|-----------|----------------|
| `test_rank_jobs.py` | Sorting, grouping by classification and country, edge cases |
| `test_report_builder.py` | HTML generation, score badges, XSS escaping |
| `test_job_search.py` | Country inference, country filtering, deduplication |
| `test_evaluate_jobs.py` | Prompt building, LLM response handling, file I/O |
| `test_email_sender.py` | Email construction, configuration validation |
| `test_parse_cv.py` | Profile extraction, LLM response handling, error cases |

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
2. Go to **Settings → Secrets and variables → Actions** and add the following repository secrets (under the **Secrets** tab):

   | Secret name | Value |
   |-------------|-------|
   | `LLM_API_KEY` | Your LLM provider API key (DeepSeek key by default) |
   | `OPENAI_API_KEY` | *(optional fallback)* OpenAI key, used only if `LLM_API_KEY` is empty |
   | `GMAIL_SENDER` | Sender Gmail address |
   | `GMAIL_APP_PASS` | Gmail App Password |
   | `GMAIL_RECIPIENT` | Recipient email address |
   | `CV_BASE64` | Your CV PDF encoded as a base64 string (see below) |

   To switch LLM provider without editing the workflow, add these as
   **repository variables** (the **Variables** tab on the same settings page):

   | Variable name | Example |
   |---------------|---------|
   | `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
   | `LLM_MODEL` | `deepseek-chat` |
   | `COUNTRY` | *(optional)* `United States` |

3. Encode your `CV.pdf` as base64 and add it as the `CV_BASE64` secret:

   **Linux / macOS:**
   ```bash
   base64 -w 0 CV.pdf
   ```

   **Windows (PowerShell):**
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("CV.pdf"))
   ```

   Copy the output and paste it as the value of the `CV_BASE64` secret in GitHub.

The workflow also supports **manual triggers**: go to **Actions → Daily Job Search → Run workflow**.

After each run, `output/report.html` and `data/jobs_scored.json` are uploaded as workflow artifacts and can be downloaded from the Actions run page.

---

## Project structure

```
CV-automation/
├── config.py                      # ← Edit this: API keys, email settings, CV path
├── main.py                        # Pipeline orchestrator
├── requirements.txt               # Python dependencies
├── cv/
│   └── CV.pdf                     # Your CV (add this yourself, not committed)
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
├── tests/
│   ├── test_rank_jobs.py          # Unit tests for ranking logic
│   ├── test_report_builder.py     # Unit tests for HTML report generation
│   ├── test_job_search.py         # Unit tests for job search & filtering
│   ├── test_evaluate_jobs.py      # Unit tests for job evaluation prompts
│   ├── test_email_sender.py       # Unit tests for email construction
│   └── test_parse_cv.py           # Unit tests for CV parsing
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
| `pytest` | Run the unit test suite |

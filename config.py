"""Central configuration for CV-automation.

Edit the values below to configure the pipeline for your account, or export
the corresponding environment variables before running (environment variables
always take precedence over values set directly in this file).

For local development you can also create a .env file – the pipeline itself
does not require python-dotenv, but any tool or shell script that loads it
will make these variables available automatically.

Quick-start
-----------
1. Drop your CV into the cv/ folder (default name: CV.pdf).
2. Fill in your OpenAI API key below (or export OPENAI_API_KEY).
3. Fill in your Gmail settings below (or export the GMAIL_* variables).
4. Run:  python main.py
"""

import os

# ---------------------------------------------------------------------------
# CV file
# ---------------------------------------------------------------------------

# Path to your CV PDF.
# Place your file inside the cv/ folder and adjust the filename if needed.
# Override with the CV_PATH environment variable when required.
# Default: "cv/CV.pdf"
CV_PATH: str = os.environ.get("CV_PATH", os.path.join("cv", "CV.pdf"))

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

# Your OpenAI API key – required for CV parsing and job evaluation.
# Get one at https://platform.openai.com/api-keys
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Gmail (SMTP)
# ---------------------------------------------------------------------------

# Gmail address used to send the daily report.
# The account must have an App Password enabled (2-Step Verification required).
GMAIL_SENDER: str = os.environ.get("GMAIL_SENDER", "")

# 16-character Gmail App Password (no spaces).
# How to create one: https://support.google.com/accounts/answer/185833
GMAIL_APP_PASS: str = os.environ.get("GMAIL_APP_PASS", "")

# Email address that will receive the daily report (can be the same as sender).
GMAIL_RECIPIENT: str = os.environ.get("GMAIL_RECIPIENT", "")

# Subject line of the daily report email.
EMAIL_SUBJECT: str = os.environ.get("EMAIL_SUBJECT", "Daily Job Search Report")

# ---------------------------------------------------------------------------
# Job search filters
# ---------------------------------------------------------------------------

# Country or region to filter job results.
# Only jobs whose inferred country/location contains this string (case-insensitive)
# will be included.  Leave blank (empty string) to include jobs from all locations.
# Examples: "United States", "United Kingdom", "Remote", "Canada"
# Override with the COUNTRY environment variable when required.
# Default: "" (no filter – all countries/regions included)
COUNTRY: str = os.environ.get("COUNTRY", "")

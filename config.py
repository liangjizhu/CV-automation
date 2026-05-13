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
2. Fill in your LLM API key below (or export LLM_API_KEY / OPENAI_API_KEY).
   By default the pipeline talks to DeepSeek; tweak LLM_BASE_URL / LLM_MODEL
   to point at any other OpenAI-compatible endpoint.
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
# LLM (OpenAI-compatible: DeepSeek, OpenAI, Together, Groq, Ollama, …)
# ---------------------------------------------------------------------------

# API key for the LLM provider – required for CV parsing and job evaluation.
# LLM_API_KEY is preferred; OPENAI_API_KEY is honoured as a fallback so
# existing setups keep working without changes.
#   • DeepSeek: https://platform.deepseek.com/api_keys
#   • OpenAI:   https://platform.openai.com/api-keys
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", ""))

# Base URL of the provider's OpenAI-compatible endpoint.
# Examples:
#   DeepSeek: "https://api.deepseek.com/v1"   (default)
#   OpenAI:   ""                              (use SDK default)
#   Groq:     "https://api.groq.com/openai/v1"
#   Ollama:   "http://localhost:11434/v1"
LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")

# Chat-completions model used by parse_cv and evaluate_jobs.
# Examples: "deepseek-chat", "deepseek-reasoner", "gpt-4o-mini",
#           "llama-3.1-70b-versatile", "llama3.1".
LLM_MODEL: str = os.environ.get("LLM_MODEL", "deepseek-v4-pro")

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
# Each term is matched case-insensitively against the inferred country and
# against the raw location string, so cities ("Berlin"), regions ("EMEA",
# "Europe"), and remote tags ("Remote", "Worldwide") all work.
#
# Multiple terms may be supplied as a comma-separated OR list:
#     "United States, Germany, Remote"   – matches jobs from any of those
# Leave blank to include jobs from every location.
# Override with the COUNTRY environment variable when required.
COUNTRY: str = os.environ.get("COUNTRY", "")

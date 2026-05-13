"""Send the HTML job report via Gmail using SMTP with an App Password."""

import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, Optional

import config

REPORT_PATH = os.path.join("output", "report.html")
EMAILED_URLS_PATH = os.path.join("data", "emailed_urls.json")


def _build_message(sender: str, recipient: str, subject: str, html_body: str) -> MIMEMultipart:
    """Construct a MIME email with an HTML body."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_via_smtp(
    sender: str,
    app_password: str,
    recipient: str,
    subject: str,
    html_body: str,
) -> None:
    """Send email using Gmail SMTP with an App Password."""
    msg = _build_message(sender, recipient, subject, html_body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.sendmail(sender, recipient, msg.as_string())

    print(f"[email_sender] Email sent to {recipient} via SMTP")


def send_email(
    report_path: str = REPORT_PATH,
    subject: str = config.EMAIL_SUBJECT,
) -> None:
    """Read configuration and send the HTML report via Gmail.

    Settings are read from config.py (which itself falls back to environment
    variables).  Required settings:
        GMAIL_SENDER     – sender Gmail address (e.g. you@gmail.com)
        GMAIL_APP_PASS   – Gmail App Password (16-char, no spaces)
        GMAIL_RECIPIENT  – recipient email address

    Optional:
        EMAIL_SUBJECT    – overrides the default subject line
    """
    sender = config.GMAIL_SENDER
    app_password = config.GMAIL_APP_PASS
    recipient = config.GMAIL_RECIPIENT

    if not sender:
        raise EnvironmentError(
            "GMAIL_SENDER is not set. Add it to config.py or export it as an environment variable."
        )
    if not app_password:
        raise EnvironmentError(
            "GMAIL_APP_PASS is not set. Add it to config.py or export it as an environment variable."
        )
    if not recipient:
        raise EnvironmentError(
            "GMAIL_RECIPIENT is not set. Add it to config.py or export it as an environment variable."
        )

    if not os.path.exists(report_path):
        raise FileNotFoundError(f"Report file not found: {report_path}")

    with open(report_path, encoding="utf-8") as fh:
        html_body = fh.read()

    send_via_smtp(sender, app_password, recipient, subject, html_body)


def _load_emailed_urls(state_path: str = EMAILED_URLS_PATH) -> set[str]:
    """Load the set of URLs that have already been emailed in a previous run.

    Returns an empty set if the state file is missing or unreadable so that
    a brand-new install simply emails every URL on the first successful send.
    """
    if not os.path.exists(state_path):
        return set()
    try:
        with open(state_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(u) for u in data} if isinstance(data, list) else set()
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[email_sender] Emailed-urls state at {state_path} unreadable ({exc}); "
            "treating as empty.",
            file=sys.stderr,
        )
        return set()


def _save_emailed_urls(urls: Iterable[str], state_path: str = EMAILED_URLS_PATH) -> None:
    """Persist the set of URLs that have been emailed."""
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(urls), fh, indent=2, ensure_ascii=False)


def send_if_new_jobs(
    scored_jobs: list[dict],
    report_path: str = REPORT_PATH,
    base_subject: Optional[str] = None,
    state_path: str = EMAILED_URLS_PATH,
) -> bool:
    """Send the daily report only if there are jobs we haven't emailed before.

    Compares the URLs in ``scored_jobs`` against ``state_path``; if the set
    contains at least one URL we haven't seen, sends the report with a subject
    augmented by the new-job count and persists the updated state.

    Returns
    -------
    bool
        True if an email was sent, False if the send was skipped because
        there were no new jobs.
    """
    if base_subject is None:
        base_subject = config.EMAIL_SUBJECT

    if not scored_jobs:
        print("[email_sender] No scored jobs in this run; skipping email.")
        return False

    current_urls = {str(j.get("url", "")).strip() for j in scored_jobs}
    current_urls.discard("")
    if not current_urls:
        print("[email_sender] No URLs found in scored jobs; skipping email.")
        return False

    emailed = _load_emailed_urls(state_path)
    new_urls = current_urls - emailed

    if not new_urls:
        print(
            f"[email_sender] No new jobs since last email "
            f"({len(current_urls)} URLs already emailed); skipping send."
        )
        return False

    subject = f"{base_subject} — {len(new_urls)} new"
    print(
        f"[email_sender] {len(new_urls)} new job(s) since last email; "
        f"sending report with subject {subject!r}."
    )
    send_email(report_path=report_path, subject=subject)

    _save_emailed_urls(emailed | new_urls, state_path)
    return True


if __name__ == "__main__":
    try:
        send_email()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

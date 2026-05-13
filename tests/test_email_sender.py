"""Unit tests for src/email_sender.py."""

import json
import os
import tempfile
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, patch

import pytest

from src.email_sender import (
    _build_message,
    _load_emailed_urls,
    _save_emailed_urls,
    send_email,
    send_if_new_jobs,
)


# ---------------------------------------------------------------------------
# _build_message
# ---------------------------------------------------------------------------

def test_build_message_headers():
    msg = _build_message(
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject="Test Subject",
        html_body="<p>Hello</p>",
    )
    assert isinstance(msg, MIMEMultipart)
    assert msg["From"] == "sender@example.com"
    assert msg["To"] == "recipient@example.com"
    assert msg["Subject"] == "Test Subject"


def test_build_message_html_body():
    html_body = "<h1>Report</h1><p>Some jobs</p>"
    msg = _build_message(
        sender="a@example.com",
        recipient="b@example.com",
        subject="Daily Job Report",
        html_body=html_body,
    )
    payload = msg.get_payload()
    # MIMEMultipart has a list of parts
    assert isinstance(payload, list)
    # The HTML body should be in one of the parts
    body_str = payload[0].get_payload(decode=True).decode("utf-8")
    assert "<h1>Report</h1>" in body_str


# ---------------------------------------------------------------------------
# send_email – configuration validation
# ---------------------------------------------------------------------------

@patch("src.email_sender.config")
def test_send_email_missing_sender(mock_config):
    mock_config.GMAIL_SENDER = ""
    mock_config.GMAIL_APP_PASS = "pass"
    mock_config.GMAIL_RECIPIENT = "r@example.com"
    mock_config.EMAIL_SUBJECT = "Subject"

    with pytest.raises(EnvironmentError, match="GMAIL_SENDER"):
        send_email(report_path="/nonexistent/report.html")


@patch("src.email_sender.config")
def test_send_email_missing_app_pass(mock_config):
    mock_config.GMAIL_SENDER = "s@example.com"
    mock_config.GMAIL_APP_PASS = ""
    mock_config.GMAIL_RECIPIENT = "r@example.com"
    mock_config.EMAIL_SUBJECT = "Subject"

    with pytest.raises(EnvironmentError, match="GMAIL_APP_PASS"):
        send_email(report_path="/nonexistent/report.html")


@patch("src.email_sender.config")
def test_send_email_missing_recipient(mock_config):
    mock_config.GMAIL_SENDER = "s@example.com"
    mock_config.GMAIL_APP_PASS = "pass"
    mock_config.GMAIL_RECIPIENT = ""
    mock_config.EMAIL_SUBJECT = "Subject"

    with pytest.raises(EnvironmentError, match="GMAIL_RECIPIENT"):
        send_email(report_path="/nonexistent/report.html")


@patch("src.email_sender.config")
def test_send_email_missing_report_file(mock_config):
    mock_config.GMAIL_SENDER = "s@example.com"
    mock_config.GMAIL_APP_PASS = "pass"
    mock_config.GMAIL_RECIPIENT = "r@example.com"
    mock_config.EMAIL_SUBJECT = "Subject"

    with pytest.raises(FileNotFoundError):
        send_email(report_path="/nonexistent/report.html")


@patch("src.email_sender.send_via_smtp")
@patch("src.email_sender.config")
def test_send_email_calls_smtp(mock_config, mock_smtp):
    mock_config.GMAIL_SENDER = "s@example.com"
    mock_config.GMAIL_APP_PASS = "apppassword"
    mock_config.GMAIL_RECIPIENT = "r@example.com"
    mock_config.EMAIL_SUBJECT = "Daily Report"

    html_content = "<p>Jobs</p>"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as fh:
        fh.write(html_content)
        report_path = fh.name

    try:
        send_email(report_path=report_path, subject="Daily Report")
        mock_smtp.assert_called_once_with(
            "s@example.com",
            "apppassword",
            "r@example.com",
            "Daily Report",
            html_content,
        )
    finally:
        os.unlink(report_path)


# ---------------------------------------------------------------------------
# emailed-URLs state file helpers
# ---------------------------------------------------------------------------

def test_load_emailed_urls_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "no.json")
        assert _load_emailed_urls(path) == set()


def test_load_emailed_urls_corrupt_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bad.json")
        with open(path, "w") as fh:
            fh.write("not json")
        assert _load_emailed_urls(path) == set()


def test_save_then_load_emailed_urls_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "urls.json")
        _save_emailed_urls({"https://b", "https://a"}, path)
        # File should contain a sorted JSON array
        with open(path) as fh:
            data = json.load(fh)
        assert data == ["https://a", "https://b"]
        assert _load_emailed_urls(path) == {"https://a", "https://b"}


# ---------------------------------------------------------------------------
# send_if_new_jobs
# ---------------------------------------------------------------------------

@patch("src.email_sender.send_email")
def test_send_if_new_jobs_first_run_sends_all(mock_send_email):
    """On the first run, every URL is new so an email is sent."""
    jobs = [
        {"url": "https://a.example.com/job1", "title": "Job 1"},
        {"url": "https://a.example.com/job2", "title": "Job 2"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "emailed.json")
        report_path = os.path.join(tmp, "report.html")
        with open(report_path, "w") as fh:
            fh.write("<html></html>")

        sent = send_if_new_jobs(
            jobs,
            report_path=report_path,
            base_subject="Daily Job Search Report",
            state_path=state_path,
        )

        assert sent is True
        mock_send_email.assert_called_once()
        kwargs = mock_send_email.call_args.kwargs
        assert kwargs["report_path"] == report_path
        assert kwargs["subject"] == "Daily Job Search Report — 2 new"

        saved = _load_emailed_urls(state_path)
        assert saved == {jobs[0]["url"], jobs[1]["url"]}


@patch("src.email_sender.send_email")
def test_send_if_new_jobs_skips_when_no_new_urls(mock_send_email):
    """When every URL is already in the state file, no email is sent."""
    jobs = [
        {"url": "https://a.example.com/job1", "title": "Job 1"},
        {"url": "https://a.example.com/job2", "title": "Job 2"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "emailed.json")
        _save_emailed_urls({jobs[0]["url"], jobs[1]["url"]}, state_path)

        sent = send_if_new_jobs(
            jobs,
            report_path=os.path.join(tmp, "missing.html"),
            base_subject="Daily Job Search Report",
            state_path=state_path,
        )

        assert sent is False
        mock_send_email.assert_not_called()


@patch("src.email_sender.send_email")
def test_send_if_new_jobs_sends_only_when_a_new_url_appears(mock_send_email):
    """Send when at least one URL is new and merge it into the state."""
    old_url = "https://a.example.com/job1"
    new_url = "https://a.example.com/job-new"
    jobs = [
        {"url": old_url, "title": "Old"},
        {"url": new_url, "title": "Brand new"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "emailed.json")
        report_path = os.path.join(tmp, "report.html")
        with open(report_path, "w") as fh:
            fh.write("<html></html>")
        _save_emailed_urls({old_url}, state_path)

        sent = send_if_new_jobs(
            jobs,
            report_path=report_path,
            base_subject="Daily Job Search Report",
            state_path=state_path,
        )

        assert sent is True
        mock_send_email.assert_called_once()
        assert (
            mock_send_email.call_args.kwargs["subject"]
            == "Daily Job Search Report — 1 new"
        )
        assert _load_emailed_urls(state_path) == {old_url, new_url}


@patch("src.email_sender.send_email")
def test_send_if_new_jobs_empty_list_skips(mock_send_email):
    sent = send_if_new_jobs([], state_path="/dev/null")
    assert sent is False
    mock_send_email.assert_not_called()


@patch("src.email_sender.send_email")
def test_send_if_new_jobs_ignores_blank_urls(mock_send_email):
    jobs = [{"url": "", "title": "No URL"}, {"title": "Also no URL"}]
    with tempfile.TemporaryDirectory() as tmp:
        state_path = os.path.join(tmp, "emailed.json")
        sent = send_if_new_jobs(jobs, state_path=state_path)
        assert sent is False
        mock_send_email.assert_not_called()

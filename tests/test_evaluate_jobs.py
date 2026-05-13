"""Unit tests for src/evaluate_jobs.py."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.evaluate_jobs import (
    _build_evaluation_prompt,
    _load_score_cache,
    _save_score_cache,
    evaluate_job,
    evaluate_jobs,
)


# ---------------------------------------------------------------------------
# _build_evaluation_prompt
# ---------------------------------------------------------------------------

def test_build_evaluation_prompt_contains_skills():
    profile = {"skills": ["Python", "Machine Learning"], "summary": "Experienced ML engineer"}
    job = {"title": "Data Scientist", "company": "ACME", "description": "We need ML skills"}
    prompt = _build_evaluation_prompt(profile, job)
    assert "Python" in prompt
    assert "Machine Learning" in prompt
    assert "Data Scientist" in prompt
    assert "ACME" in prompt
    assert "We need ML skills" in prompt


def test_build_evaluation_prompt_truncates_description():
    profile = {"skills": ["Python"], "summary": ""}
    long_description = "x" * 5000
    job = {"title": "Job", "company": "Co", "description": long_description}
    prompt = _build_evaluation_prompt(profile, job)
    # Description is truncated to _MAX_DESC_CHARS (3000)
    assert long_description not in prompt
    assert "x" * 3000 in prompt


def test_build_evaluation_prompt_empty_profile():
    profile = {}
    job = {"title": "Analyst", "company": "Firm", "description": "Finance role"}
    prompt = _build_evaluation_prompt(profile, job)
    assert "Analyst" in prompt
    assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# evaluate_job – mocking OpenAI client
# ---------------------------------------------------------------------------

def _make_mock_client(content: str) -> MagicMock:
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    client.chat.completions.create.return_value.choices = [choice]
    return client


def test_evaluate_job_success():
    profile = {"skills": ["Python"], "summary": "Developer"}
    job = {"title": "Engineer", "company": "Co", "description": "Python job", "url": "https://co.com"}
    llm_response = json.dumps({"score": 8, "classification": "industry", "reasoning": "Good match"})

    client = _make_mock_client(llm_response)
    result = evaluate_job(profile, job, client)

    assert result["score"] == 8
    assert result["classification"] == "industry"
    assert result["reasoning"] == "Good match"
    assert result["title"] == "Engineer"


def test_evaluate_job_none_content():
    """LLM returning None content should produce score 0."""
    profile = {"skills": ["Python"], "summary": "Developer"}
    job = {"title": "Engineer", "company": "Co", "description": "desc", "url": ""}
    client = _make_mock_client(None)

    result = evaluate_job(profile, job, client)
    assert result["score"] == 0
    assert result["classification"] == "unknown"


def test_evaluate_job_invalid_json():
    """LLM returning invalid JSON should produce score 0."""
    profile = {"skills": ["Go"], "summary": "Engineer"}
    job = {"title": "Backend", "company": "X", "description": "desc", "url": ""}
    client = _make_mock_client("this is not json")

    result = evaluate_job(profile, job, client)
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# evaluate_jobs – integration with file I/O
# ---------------------------------------------------------------------------

@patch("src.evaluate_jobs.config")
@patch("src.evaluate_jobs.OpenAI")
def test_evaluate_jobs_saves_scored(mock_openai_cls, mock_config):
    mock_config.LLM_API_KEY = "test-key"
    mock_config.LLM_BASE_URL = ""
    mock_config.LLM_MODEL = "deepseek-chat"

    llm_content = json.dumps({"score": 7, "classification": "research", "reasoning": "Nice"})
    mock_client = _make_mock_client(llm_content)
    mock_openai_cls.return_value = mock_client

    profile = {"skills": ["Python"], "summary": "Dev"}
    jobs = [{"title": "Researcher", "company": "Uni", "description": "AI research", "url": ""}]

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        jobs_raw_path = os.path.join(tmpdir, "jobs_raw.json")
        jobs_scored_path = os.path.join(tmpdir, "jobs_scored.json")
        cache_path = os.path.join(tmpdir, "scored_cache.json")

        with open(profile_path, "w") as fh:
            json.dump(profile, fh)
        with open(jobs_raw_path, "w") as fh:
            json.dump(jobs, fh)

        with patch("src.evaluate_jobs.JOBS_SCORED_PATH", jobs_scored_path), \
             patch("src.evaluate_jobs.SCORE_CACHE_PATH", cache_path):
            result = evaluate_jobs(profile_path=profile_path, jobs_raw_path=jobs_raw_path)

        assert len(result) == 1
        assert result[0]["score"] == 7
        assert os.path.exists(jobs_scored_path)


@patch("src.evaluate_jobs.config")
def test_evaluate_jobs_no_api_key_uses_defaults(mock_config):
    """When LLM_API_KEY is missing, jobs are returned with default scores."""
    mock_config.LLM_API_KEY = ""
    profile = {"skills": ["Python"], "summary": "Dev"}
    jobs = [{"title": "Researcher", "company": "Uni", "description": "AI research", "url": ""}]

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        jobs_raw_path = os.path.join(tmpdir, "jobs_raw.json")
        jobs_scored_path = os.path.join(tmpdir, "jobs_scored.json")

        with open(profile_path, "w") as fh:
            json.dump(profile, fh)
        with open(jobs_raw_path, "w") as fh:
            json.dump(jobs, fh)

        with patch("src.evaluate_jobs.JOBS_SCORED_PATH", jobs_scored_path):
            result = evaluate_jobs(profile_path=profile_path, jobs_raw_path=jobs_raw_path)

        assert len(result) == 1
        assert result[0]["score"] == 0
        assert result[0]["classification"] == "unscored"
        assert os.path.exists(jobs_scored_path)


def test_evaluate_jobs_missing_file():
    with patch("src.evaluate_jobs.config") as mock_config:
        mock_config.LLM_API_KEY = "key"
        mock_config.LLM_BASE_URL = ""
        mock_config.LLM_MODEL = "deepseek-chat"
        with pytest.raises(FileNotFoundError):
            evaluate_jobs(
                profile_path="/nonexistent/profile.json",
                jobs_raw_path="/nonexistent/jobs_raw.json",
            )


# ---------------------------------------------------------------------------
# Score cache
# ---------------------------------------------------------------------------

def test_load_score_cache_missing_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        assert _load_score_cache(os.path.join(tmp, "missing.json")) == {}


def test_load_score_cache_corrupt_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bad.json")
        with open(path, "w") as fh:
            fh.write("not json")
        assert _load_score_cache(path) == {}


def test_save_then_load_score_cache_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.json")
        cache = {
            "https://co/job1": {"score": 8, "classification": "industry", "reasoning": "ok"},
        }
        _save_score_cache(cache, path)
        assert _load_score_cache(path) == cache


@patch("src.evaluate_jobs.config")
@patch("src.evaluate_jobs.OpenAI")
def test_evaluate_jobs_uses_cache_for_known_urls(mock_openai_cls, mock_config):
    """Jobs whose URL is in the cache should not trigger an LLM call."""
    mock_config.LLM_API_KEY = "test-key"
    mock_config.LLM_BASE_URL = ""
    mock_config.LLM_MODEL = "deepseek-chat"

    mock_client = _make_mock_client(json.dumps({
        "score": 9, "classification": "industry", "reasoning": "fresh",
    }))
    mock_openai_cls.return_value = mock_client

    profile = {"skills": ["Python"], "summary": "Dev"}
    cached_url = "https://co/cached"
    new_url = "https://co/new"
    jobs = [
        {"title": "Cached", "company": "Old", "description": "x", "url": cached_url},
        {"title": "New", "company": "Co", "description": "y", "url": new_url},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        profile_path = os.path.join(tmp, "profile.json")
        jobs_raw_path = os.path.join(tmp, "jobs_raw.json")
        jobs_scored_path = os.path.join(tmp, "jobs_scored.json")
        cache_path = os.path.join(tmp, "scored_cache.json")

        with open(profile_path, "w") as fh:
            json.dump(profile, fh)
        with open(jobs_raw_path, "w") as fh:
            json.dump(jobs, fh)

        # Pre-seed the cache with one of the URLs
        _save_score_cache({
            cached_url: {"score": 7, "classification": "research", "reasoning": "cached"},
        }, cache_path)

        with patch("src.evaluate_jobs.JOBS_SCORED_PATH", jobs_scored_path), \
             patch("src.evaluate_jobs.SCORE_CACHE_PATH", cache_path):
            result = evaluate_jobs(profile_path=profile_path, jobs_raw_path=jobs_raw_path)

        # LLM should have been called exactly once: only for the new URL
        assert mock_client.chat.completions.create.call_count == 1

        scored_by_url = {j["url"]: j for j in result}
        assert scored_by_url[cached_url]["score"] == 7
        assert scored_by_url[cached_url]["reasoning"] == "cached"
        assert scored_by_url[new_url]["score"] == 9

        # Cache should now contain both URLs
        updated_cache = _load_score_cache(cache_path)
        assert set(updated_cache) == {cached_url, new_url}

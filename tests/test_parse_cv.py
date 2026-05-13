"""Unit tests for src/parse_cv.py."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.parse_cv import extract_skills_with_llm, parse_cv, _extract_profile_without_llm


# ---------------------------------------------------------------------------
# extract_skills_with_llm
# ---------------------------------------------------------------------------

def _make_mock_client(content: str) -> MagicMock:
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    client.chat.completions.create.return_value.choices = [choice]
    return client


def test_extract_skills_valid_json():
    profile_data = {
        "name": "Jane Doe",
        "skills": ["Python", "Machine Learning"],
        "experience_years": 5,
        "education": ["PhD Computer Science"],
        "languages": ["English"],
        "summary": "Experienced researcher.",
    }
    client = _make_mock_client(json.dumps(profile_data))
    result = extract_skills_with_llm("some cv text", client)
    assert result["name"] == "Jane Doe"
    assert "Python" in result["skills"]
    assert result["experience_years"] == 5


def test_extract_skills_none_content():
    """None response content should raise ValueError."""
    client = _make_mock_client(None)
    with pytest.raises(ValueError, match="None"):
        extract_skills_with_llm("some cv text", client)


def test_extract_skills_invalid_json():
    """Invalid JSON from the LLM should raise ValueError."""
    client = _make_mock_client("not json at all")
    with pytest.raises(ValueError, match="invalid JSON"):
        extract_skills_with_llm("some cv text", client)


# ---------------------------------------------------------------------------
# _extract_profile_without_llm
# ---------------------------------------------------------------------------

def test_extract_profile_without_llm_finds_known_skills():
    cv_text = "Experienced Python developer with Docker and AWS knowledge."
    result = _extract_profile_without_llm(cv_text)
    assert "Python" in result["skills"]
    assert "Docker" in result["skills"]
    assert "AWS" in result["skills"]


def test_extract_profile_without_llm_empty_text():
    result = _extract_profile_without_llm("")
    assert isinstance(result["skills"], list)
    assert result["name"] == "Unknown"


# ---------------------------------------------------------------------------
# parse_cv – integration
# ---------------------------------------------------------------------------

@patch("src.parse_cv.config")
@patch("src.parse_cv.OpenAI")
@patch("src.parse_cv.extract_text_from_pdf")
def test_parse_cv_saves_profile(mock_extract_text, mock_openai_cls, mock_config):
    mock_config.LLM_API_KEY = "test-key"
    mock_config.LLM_BASE_URL = ""
    mock_config.LLM_MODEL = "deepseek-chat"
    mock_config.CV_PATH = "cv/CV.pdf"
    mock_extract_text.return_value = "Jane Doe, Python developer"

    profile_data = {
        "name": "Jane Doe",
        "skills": ["Python"],
        "experience_years": 3,
        "education": ["BSc"],
        "languages": ["English"],
        "summary": "Python dev.",
    }
    mock_client = _make_mock_client(json.dumps(profile_data))
    mock_openai_cls.return_value = mock_client

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        with patch("src.parse_cv.PROFILE_PATH", profile_path):
            # Also patch os.makedirs so it writes to tmpdir
            result = parse_cv(cv_path="cv/CV.pdf")

        assert result["name"] == "Jane Doe"
        assert os.path.exists(profile_path)
        with open(profile_path) as fh:
            saved = json.load(fh)
        assert saved["name"] == "Jane Doe"


@patch("src.parse_cv.config")
def test_parse_cv_no_api_key_falls_back_to_existing_profile(mock_config):
    """When LLM_API_KEY is missing but profile.json exists, load from it."""
    mock_config.LLM_API_KEY = ""
    mock_config.CV_PATH = "cv/CV.pdf"
    saved_profile = {"name": "Jane", "skills": ["Python"], "summary": "Dev"}

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        with open(profile_path, "w") as fh:
            json.dump(saved_profile, fh)

        with patch("src.parse_cv.PROFILE_PATH", profile_path):
            result = parse_cv(cv_path="cv/CV.pdf")

    assert result["name"] == "Jane"
    assert "Python" in result["skills"]


@patch("src.parse_cv.extract_text_from_pdf")
@patch("src.parse_cv.config")
def test_parse_cv_no_api_key_uses_keyword_extraction(mock_config, mock_extract_text):
    """When API key and profile are both absent, keyword extraction is used."""
    mock_config.LLM_API_KEY = ""
    mock_config.CV_PATH = "cv/CV.pdf"
    mock_extract_text.return_value = "Experienced Python and Docker developer"

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        # No pre-existing profile.json

        with patch("src.parse_cv.PROFILE_PATH", profile_path):
            result = parse_cv(cv_path="cv/CV.pdf")

        assert "Python" in result["skills"]
        assert "Docker" in result["skills"]
        assert os.path.exists(profile_path)


@patch("src.parse_cv.config")
@patch("src.parse_cv.OpenAI")
def test_parse_cv_missing_pdf(mock_openai_cls, mock_config):
    mock_config.LLM_API_KEY = "test-key"
    mock_config.LLM_BASE_URL = ""
    mock_config.LLM_MODEL = "deepseek-chat"
    mock_openai_cls.return_value = MagicMock()

    with pytest.raises(FileNotFoundError):
        parse_cv(cv_path="/nonexistent/CV.pdf")

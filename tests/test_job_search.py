"""Unit tests for src/job_search.py."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.job_search import (
    _infer_country,
    _matches_country_filter,
    _parse_country_filter,
    _parse_hn_location,
    run,
    search_arbeitnow,
    search_jobicy,
    search_jobs,
    search_remoteok,
)


# ---------------------------------------------------------------------------
# Decorator stack used by every search_jobs integration test.
#
# search_jobs now consults five sources; tests mock every one so no real
# HTTP request is ever made. Mocks default to returning empty lists; the
# specific tests below override only the sources they care about.
# ---------------------------------------------------------------------------

def _patch_all_sources(test_fn):
    """Apply five @patch decorators in the right order for the underlying test."""
    decorators = [
        patch("src.job_search.search_remotive"),
        patch("src.job_search.search_hn_who_is_hiring"),
        patch("src.job_search.search_arbeitnow"),
        patch("src.job_search.search_remoteok"),
        patch("src.job_search.search_jobicy"),
        patch("src.job_search.config"),
    ]
    for dec in reversed(decorators):
        test_fn = dec(test_fn)
    return test_fn


# ---------------------------------------------------------------------------
# _infer_country
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location,expected", [
    ("USA", "United States"),
    ("United States", "United States"),
    ("US only", "United States"),
    ("uk", "United Kingdom"),
    ("United Kingdom", "United Kingdom"),
    ("Canada", "Canada"),
    ("Germany", "Germany"),
    ("France", "France"),
    ("Australia", "Australia"),
    ("Remote", "Remote"),
    ("Worldwide", "Remote"),
    ("Anywhere", "Remote"),
    ("Singapore", "Singapore"),
    ("", "Unknown"),
    # New cases enabled by the expanded mapping
    ("Berlin, DE", "Germany"),
    ("San Francisco, CA", "United States"),
    ("New York, NY", "United States"),
    ("London", "United Kingdom"),
    ("Paris, France", "France"),
    ("Madrid", "Spain"),
    ("Toronto, ON", "Canada"),
    ("Tokyo", "Japan"),
    ("Zurich", "Switzerland"),
    ("EMEA", "Remote"),
    ("APAC", "Remote"),
    ("Europe", "Europe"),
    # Regression: 'us' must not match inside 'australia'
    ("Australia", "Australia"),
])
def test_infer_country(location, expected):
    assert _infer_country(location) == expected


# ---------------------------------------------------------------------------
# _parse_hn_location
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_country,expected_loc_contains", [
    ("Location: Berlin, Germany\nWe build AI tools.", "Germany", "Berlin"),
    # 'Remote (US)' is ambiguous; longest-match wins so 'Remote' beats 'US'.
    ("LOCATION - Remote (US)\nFully remote", "Remote", "Remote"),
    ("Where: London, UK\nCool company", "United Kingdom", "London"),
    ("ACME | Senior Engineer | REMOTE\n", "Remote", "REMOTE"),
    ("No location info here at all about anything", "Unknown", ""),
])
def test_parse_hn_location_extracts_known_locations(text, expected_country, expected_loc_contains):
    parsed = _parse_hn_location(text)
    if expected_loc_contains:
        assert expected_loc_contains.lower() in parsed.lower()
        assert _infer_country(parsed) == expected_country
    else:
        assert parsed == ""


# ---------------------------------------------------------------------------
# _parse_country_filter / _matches_country_filter
# ---------------------------------------------------------------------------

def test_parse_country_filter_splits_on_comma():
    assert _parse_country_filter("United States, Germany ,Remote") == [
        "united states", "germany", "remote",
    ]


def test_parse_country_filter_handles_blank():
    assert _parse_country_filter("") == []
    assert _parse_country_filter(None) == []
    assert _parse_country_filter("   ") == []


def test_matches_country_filter_empty_terms_keeps_everything():
    job = {"country": "Germany", "location": "Berlin"}
    assert _matches_country_filter(job, []) is True


def test_matches_country_filter_or_match():
    job = {"country": "United States", "location": "New York"}
    assert _matches_country_filter(job, ["germany", "united states"]) is True
    assert _matches_country_filter(job, ["germany", "spain"]) is False


def test_matches_country_filter_checks_location_too():
    job = {"country": "Unknown", "location": "Remote / Berlin"}
    assert _matches_country_filter(job, ["berlin"]) is True
    assert _matches_country_filter(job, ["unknown"]) is True


# ---------------------------------------------------------------------------
# search_jobs – aggregation, filtering, dedup
# ---------------------------------------------------------------------------

_SAMPLE_JOBS = [
    {"title": "A", "company": "X", "location": "Remote", "country": "Remote",
     "description": "desc", "url": "https://a.com", "source": "remotive", "category": ""},
    {"title": "B", "company": "Y", "location": "New York, USA", "country": "United States",
     "description": "desc", "url": "https://b.com", "source": "remotive", "category": ""},
    {"title": "C", "company": "Z", "location": "Berlin", "country": "Germany",
     "description": "desc", "url": "https://c.com", "source": "remotive", "category": ""},
]


@_patch_all_sources
def test_search_jobs_no_filter(mock_config, mock_jobicy, mock_remoteok, mock_arbeitnow,
                               mock_hn, mock_remotive):
    mock_config.COUNTRY = ""
    mock_remotive.return_value = _SAMPLE_JOBS
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python", "ML"]}
    result = search_jobs(profile)
    assert len(result) == 3


@_patch_all_sources
def test_search_jobs_country_filter(mock_config, mock_jobicy, mock_remoteok, mock_arbeitnow,
                                    mock_hn, mock_remotive):
    mock_config.COUNTRY = "United States"
    mock_remotive.return_value = _SAMPLE_JOBS
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    assert len(result) == 1
    assert result[0]["title"] == "B"


@_patch_all_sources
def test_search_jobs_country_filter_case_insensitive(mock_config, mock_jobicy, mock_remoteok,
                                                     mock_arbeitnow, mock_hn, mock_remotive):
    mock_config.COUNTRY = "remote"
    mock_remotive.return_value = _SAMPLE_JOBS
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    assert len(result) == 1
    assert result[0]["title"] == "A"


@_patch_all_sources
def test_search_jobs_multi_value_country_filter(mock_config, mock_jobicy, mock_remoteok,
                                                mock_arbeitnow, mock_hn, mock_remotive):
    """Comma-separated COUNTRY should OR-match each term."""
    mock_config.COUNTRY = "Germany, Remote"
    mock_remotive.return_value = _SAMPLE_JOBS
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    titles = sorted(j["title"] for j in result)
    assert titles == ["A", "C"]


@_patch_all_sources
def test_search_jobs_aggregates_multiple_sources(mock_config, mock_jobicy, mock_remoteok,
                                                 mock_arbeitnow, mock_hn, mock_remotive):
    """Every source's contribution should appear in the aggregated list."""
    mock_config.COUNTRY = ""
    mock_remotive.return_value = [_SAMPLE_JOBS[0]]
    mock_hn.return_value = []
    mock_arbeitnow.return_value = [_SAMPLE_JOBS[1]]
    mock_remoteok.return_value = []
    mock_jobicy.return_value = [_SAMPLE_JOBS[2]]

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    sources = sorted({j["source"] for j in result})
    assert sources == ["remotive"]  # all sample jobs share source field
    assert len(result) == 3


@_patch_all_sources
def test_search_jobs_resilient_to_source_crash(mock_config, mock_jobicy, mock_remoteok,
                                               mock_arbeitnow, mock_hn, mock_remotive):
    """A crashing source must not bring the whole pipeline down."""
    mock_config.COUNTRY = ""
    mock_remotive.return_value = [_SAMPLE_JOBS[0]]
    mock_hn.side_effect = RuntimeError("HN exploded")
    mock_arbeitnow.return_value = [_SAMPLE_JOBS[1]]
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    assert len(result) == 2


@_patch_all_sources
def test_search_jobs_deduplication(mock_config, mock_jobicy, mock_remoteok, mock_arbeitnow,
                                   mock_hn, mock_remotive):
    """Jobs with the same URL should be deduplicated."""
    mock_config.COUNTRY = ""
    duplicate = dict(_SAMPLE_JOBS[0])
    mock_remotive.return_value = [_SAMPLE_JOBS[0], duplicate]
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    profile = {"skills": ["Python"]}
    result = search_jobs(profile)
    assert len(result) == 1


@_patch_all_sources
def test_search_jobs_no_skills_raises(mock_config, mock_jobicy, mock_remoteok, mock_arbeitnow,
                                      mock_hn, mock_remotive):
    mock_config.COUNTRY = ""
    mock_remotive.return_value = []
    mock_hn.return_value = []
    mock_arbeitnow.return_value = []
    mock_remoteok.return_value = []
    mock_jobicy.return_value = []

    with pytest.raises(ValueError, match="no skills"):
        search_jobs({"skills": []})


# ---------------------------------------------------------------------------
# Source: Arbeitnow
# ---------------------------------------------------------------------------

@patch("src.job_search._get")
def test_search_arbeitnow_filters_by_keyword(mock_get):
    payload = {
        "data": [
            {
                "title": "Senior Python Engineer",
                "company_name": "Acme",
                "description": "<p>Python and Django</p>",
                "tags": ["python", "django"],
                "location": "Berlin, Germany",
                "url": "https://arbeitnow.com/jobs/python-1",
                "remote": False,
            },
            {
                "title": "iOS Developer",
                "company_name": "Other",
                "description": "<p>Swift only</p>",
                "tags": ["swift", "ios"],
                "location": "Munich, Germany",
                "url": "https://arbeitnow.com/jobs/ios-2",
                "remote": True,
            },
        ]
    }
    response = MagicMock()
    response.json.return_value = payload
    mock_get.return_value = response

    result = search_arbeitnow(["Python"])
    assert len(result) == 1
    assert result[0]["title"] == "Senior Python Engineer"
    assert result[0]["country"] == "Germany"
    assert result[0]["source"] == "arbeitnow"


@patch("src.job_search._get")
def test_search_arbeitnow_handles_failure_gracefully(mock_get):
    mock_get.side_effect = RuntimeError("network down")
    assert search_arbeitnow(["Python"]) == []


# ---------------------------------------------------------------------------
# Source: RemoteOK
# ---------------------------------------------------------------------------

@patch("src.job_search._get")
def test_search_remoteok_skips_metadata_element(mock_get):
    payload = [
        {"legal": "RemoteOK metadata banner"},
        {
            "id": "1",
            "position": "Senior Backend Engineer",
            "company": "Acme",
            "description": "<p>Python backend</p>",
            "tags": ["python", "backend"],
            "location": "Worldwide",
            "url": "https://remoteok.com/job/1",
        },
        {
            "id": "2",
            "position": "Designer",
            "company": "Other",
            "description": "<p>Figma</p>",
            "tags": ["figma"],
            "location": "Worldwide",
            "url": "https://remoteok.com/job/2",
        },
    ]
    response = MagicMock()
    response.json.return_value = payload
    mock_get.return_value = response

    result = search_remoteok(["Python"])
    assert len(result) == 1
    assert result[0]["title"] == "Senior Backend Engineer"
    assert result[0]["source"] == "remoteok"
    assert result[0]["country"] == "Remote"


@patch("src.job_search._get")
def test_search_remoteok_handles_non_list_response(mock_get):
    response = MagicMock()
    response.json.return_value = {"unexpected": "shape"}
    mock_get.return_value = response

    assert search_remoteok(["Python"]) == []


# ---------------------------------------------------------------------------
# Source: Jobicy
# ---------------------------------------------------------------------------

@patch("src.job_search._get")
def test_search_jobicy_dedupes_across_tags(mock_get):
    """Jobicy is queried once per top skill; duplicates across tags are merged."""
    payload = {
        "jobs": [
            {
                "id": "1",
                "jobTitle": "Python Dev",
                "companyName": "Acme",
                "jobDescription": "<p>Python</p>",
                "jobIndustry": ["IT"],
                "jobGeo": "USA",
                "url": "https://jobicy.com/jobs/1",
            },
            {
                "id": "2",
                "jobTitle": "Backend Dev",
                "companyName": "Other",
                "jobDescription": "<p>Backend</p>",
                "jobIndustry": ["IT"],
                "jobGeo": "Germany",
                "url": "https://jobicy.com/jobs/2",
            },
        ]
    }
    response = MagicMock()
    response.json.return_value = payload
    mock_get.return_value = response

    result = search_jobicy(["python", "backend"])
    # Two distinct jobs even though we hit the API twice
    assert len(result) == 2
    countries = sorted(j["country"] for j in result)
    assert countries == ["Germany", "United States"]


@patch("src.job_search._get")
def test_search_jobicy_handles_failure(mock_get):
    mock_get.side_effect = RuntimeError("rate limited")
    assert search_jobicy(["python"]) == []


# ---------------------------------------------------------------------------
# run – integration with file I/O
# ---------------------------------------------------------------------------

@patch("src.job_search.search_jobs")
def test_run_saves_jobs(mock_search_jobs):
    mock_search_jobs.return_value = [
        {"title": "X", "url": "https://x.com", "source": "remotive"}
    ]

    profile = {"skills": ["Python"]}
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = os.path.join(tmpdir, "profile.json")
        jobs_path = os.path.join(tmpdir, "jobs_raw.json")
        with open(profile_path, "w") as fh:
            json.dump(profile, fh)

        with patch("src.job_search.JOBS_RAW_PATH", jobs_path):
            result = run(profile_path=profile_path)

        assert len(result) == 1
        assert os.path.exists(jobs_path)
        with open(jobs_path) as fh:
            saved = json.load(fh)
        assert saved[0]["title"] == "X"


def test_run_missing_profile():
    with pytest.raises(FileNotFoundError):
        run(profile_path="/nonexistent/profile.json")

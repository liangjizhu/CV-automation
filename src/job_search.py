"""Search job websites for relevant positions based on a candidate profile."""

import json
import os
import sys
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

import config

PROFILE_PATH = os.path.join("data", "profile.json")
JOBS_RAW_PATH = os.path.join("data", "jobs_raw.json")

# Headers that mimic a regular browser to reduce bot-blocking
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_REQUEST_TIMEOUT = 15  # seconds
_DELAY_BETWEEN_REQUESTS = 2  # seconds


def _get(url: str, params: Optional[dict] = None) -> requests.Response:
    """Perform a GET request with error handling and a polite delay."""
    time.sleep(_DELAY_BETWEEN_REQUESTS)
    response = requests.get(
        url,
        params=params,
        headers=_HEADERS,
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response


def search_remotive(keywords: list[str]) -> list[dict]:
    """Search Remotive.io (JSON API, no auth required) for remote tech jobs."""
    query = " ".join(keywords[:5])
    url = "https://remotive.com/api/remote-jobs"
    jobs = []

    try:
        response = _get(url, params={"search": query, "limit": 50})
        data = response.json()
        for job in data.get("jobs", []):
            jobs.append(
                {
                    "title": job.get("title", ""),
                    "company": job.get("company_name", ""),
                    "location": job.get("candidate_required_location", "Remote"),
                    "country": _infer_country(
                        job.get("candidate_required_location", "")
                    ),
                    "description": BeautifulSoup(
                        job.get("description", ""), "html.parser"
                    ).get_text(separator=" "),
                    "url": job.get("url", ""),
                    "source": "remotive",
                    "category": job.get("category", ""),
                }
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_search] Remotive search failed: {exc}", file=sys.stderr)

    return jobs


def search_hn_who_is_hiring(keywords: list[str]) -> list[dict]:
    """Scrape the Hacker News 'Who is Hiring?' thread via Algolia HN API."""
    url = "https://hn.algolia.com/api/v1/search"
    jobs = []
    keyword_str = " ".join(keywords[:3])

    try:
        response = _get(
            url,
            params={
                "query": f"who is hiring {keyword_str}",
                "tags": "story",
                "hitsPerPage": 1,
            },
        )
        hits = response.json().get("hits", [])
        if not hits:
            return jobs

        thread_id = hits[0].get("objectID")

        comments_resp = _get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "tags": f"comment,story_{thread_id}",
                "query": keyword_str,
                "hitsPerPage": 50,
            },
        )
        for comment in comments_resp.json().get("hits", []):
            text = BeautifulSoup(
                comment.get("comment_text", ""), "html.parser"
            ).get_text(separator=" ")
            jobs.append(
                {
                    "title": "Software Engineer (HN)",
                    "company": "Unknown",
                    "location": "Remote / Unknown",
                    "country": "Unknown",
                    "description": text[:2000],
                    "url": f"https://news.ycombinator.com/item?id={comment.get('objectID')}",
                    "source": "hackernews",
                    "category": "",
                }
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_search] HN search failed: {exc}", file=sys.stderr)

    return jobs


def _infer_country(location: str) -> str:
    """Best-effort mapping from a location string to a country name."""
    location_lower = location.lower()
    mappings = {
        "usa": "United States",
        "us": "United States",
        "united states": "United States",
        "uk": "United Kingdom",
        "united kingdom": "United Kingdom",
        "canada": "Canada",
        "germany": "Germany",
        "france": "France",
        "australia": "Australia",
        "remote": "Remote",
        "worldwide": "Remote",
        "anywhere": "Remote",
    }
    for key, country in mappings.items():
        if key in location_lower:
            return country
    return location or "Unknown"


def search_jobs(profile: dict) -> list[dict]:
    """Run all job search sources and return a combined, deduplicated list."""
    skills = profile.get("skills", [])
    if not skills:
        raise ValueError("Profile contains no skills to search with")

    keywords = skills[:10]

    print(f"[job_search] Searching with keywords: {keywords}")

    country_filter = (config.COUNTRY or "").strip()
    if country_filter:
        print(f"[job_search] Filtering by country/region: {country_filter!r}")

    all_jobs: list[dict] = []
    all_jobs.extend(search_remotive(keywords))
    all_jobs.extend(search_hn_who_is_hiring(keywords))

    # Apply country/region filter when configured
    if country_filter:
        country_filter_lower = country_filter.lower()
        all_jobs = [
            job
            for job in all_jobs
            if country_filter_lower in job.get("country", "").lower()
            or country_filter_lower in job.get("location", "").lower()
        ]
        print(f"[job_search] {len(all_jobs)} jobs remaining after country filter")

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_jobs = []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_jobs.append(job)
        elif not url:
            unique_jobs.append(job)

    print(f"[job_search] Found {len(unique_jobs)} unique job listings")
    return unique_jobs


def run(profile_path: str = PROFILE_PATH) -> list[dict]:
    """Load profile, search jobs, save raw results, and return them."""
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    with open(profile_path, encoding="utf-8") as fh:
        profile = json.load(fh)

    jobs = search_jobs(profile)

    os.makedirs("data", exist_ok=True)
    with open(JOBS_RAW_PATH, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2, ensure_ascii=False)

    print(f"[job_search] Raw jobs saved to {JOBS_RAW_PATH}")
    return jobs


if __name__ == "__main__":
    try:
        result = run()
        print(f"Found {len(result)} jobs")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

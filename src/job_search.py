"""Search job websites for relevant positions based on a candidate profile.

The module aggregates jobs from several free, no-auth APIs:

* Remotive.io           – remote-only job board (JSON API, server-side search)
* Hacker News           – the monthly "Who is hiring?" thread (Algolia API)
* Arbeitnow.com         – EU-focused job board (JSON API, client-side filter)
* RemoteOK              – global remote jobs (JSON API, client-side filter)
* Jobicy                – remote jobs with geo tagging (JSON API, tag filter)

Each source produces a uniform job dict with at least: ``title``, ``company``,
``location``, ``country``, ``description``, ``url``, ``source``, ``category``.
The aggregated list is then deduplicated by URL and (optionally) filtered by
``config.COUNTRY``, which now supports a comma-separated list of terms
(any-of match).
"""

import json
import os
import re
import sys
import time
from typing import Callable, Optional

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


# ---------------------------------------------------------------------------
# Country / region inference
# ---------------------------------------------------------------------------

# Mapping of canonical lowercase keywords to a normalised country/region label.
# Longer keys are matched first so that "united states" wins over "us".
# Word boundaries are enforced so that "us" never matches inside "australia".
_LOCATION_KEYWORDS: dict[str, str] = {
    # Multi-word country names (matched before short codes)
    "united states of america": "United States",
    "united states": "United States",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "new zealand": "New Zealand",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "north america": "North America",
    "south america": "South America",
    "latin america": "Latin America",
    "middle east": "Middle East",
    "czech republic": "Czechia",
    # Single-word countries
    "deutschland": "Germany",
    "switzerland": "Switzerland",
    "netherlands": "Netherlands",
    "australia": "Australia",
    "argentina": "Argentina",
    "singapore": "Singapore",
    "portugal": "Portugal",
    "denmark": "Denmark",
    "finland": "Finland",
    "norway": "Norway",
    "sweden": "Sweden",
    "germany": "Germany",
    "france": "France",
    "canada": "Canada",
    "ireland": "Ireland",
    "poland": "Poland",
    "spain": "Spain",
    "italy": "Italy",
    "japan": "Japan",
    "india": "India",
    "china": "China",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "austria": "Austria",
    "belgium": "Belgium",
    "estonia": "Estonia",
    "greece": "Greece",
    "hungary": "Hungary",
    "iceland": "Iceland",
    "israel": "Israel",
    "luxembourg": "Luxembourg",
    "romania": "Romania",
    "russia": "Russia",
    "turkey": "Turkey",
    "ukraine": "Ukraine",
    "holland": "Netherlands",
    "espana": "Spain",
    # Country codes / abbreviations
    "u.s.a.": "United States",
    "u.s.a": "United States",
    "u.s.": "United States",
    "u.k.": "United Kingdom",
    "usa": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    # Major cities → country
    "amsterdam": "Netherlands",
    "barcelona": "Spain",
    "bangalore": "India",
    "berlin": "Germany",
    "boston": "United States",
    "buenos aires": "Argentina",
    "chicago": "United States",
    "copenhagen": "Denmark",
    "dublin": "Ireland",
    "frankfurt": "Germany",
    "geneva": "Switzerland",
    "hamburg": "Germany",
    "helsinki": "Finland",
    "lisbon": "Portugal",
    "london": "United Kingdom",
    "los angeles": "United States",
    "madrid": "Spain",
    "melbourne": "Australia",
    "mumbai": "India",
    "munich": "Germany",
    "new york": "United States",
    "nyc": "United States",
    "oslo": "Norway",
    "paris": "France",
    "prague": "Czechia",
    "san francisco": "United States",
    "seattle": "United States",
    "singapore city": "Singapore",
    "sao paulo": "Brazil",
    "stockholm": "Sweden",
    "sydney": "Australia",
    "tel aviv": "Israel",
    "tokyo": "Japan",
    "toronto": "Canada",
    "vancouver": "Canada",
    "warsaw": "Poland",
    "zurich": "Switzerland",
    # Multi-region / remote markers (kept distinct so users can filter them)
    "americas": "Remote",
    "anywhere": "Remote",
    "apac": "Remote",
    "emea": "Remote",
    "europe": "Europe",
    "global": "Remote",
    "remote": "Remote",
    "worldwide": "Remote",
}

# Pre-sort keys longest-first so multi-word keys win before short codes.
_LOCATION_KEYS_LONGEST_FIRST: tuple[str, ...] = tuple(
    sorted(_LOCATION_KEYWORDS, key=len, reverse=True)
)


def _infer_country(location: str) -> str:
    """Best-effort mapping from a location string to a country/region label.

    The function scans ``location`` for known country names, common ISO codes,
    major cities, and remote-region tags; matches use word boundaries so
    "us" won't match inside "australia". When nothing matches, the original
    string is returned (or "Unknown" if it was empty).
    """
    if not location:
        return "Unknown"
    location_lower = location.lower()
    for key in _LOCATION_KEYS_LONGEST_FIRST:
        if re.search(r"\b" + re.escape(key) + r"\b", location_lower):
            return _LOCATION_KEYWORDS[key]
    return location.strip() or "Unknown"


# Regex used to pull a "Location:" line out of a Hacker News job comment.
# Matches lines like "Location: Berlin, Germany", "LOCATION - Remote (US)",
# "Where: New York, NY", etc.
_HN_LOCATION_RE = re.compile(
    r"(?:^|\n)\s*(?:location|where)[:\-]?\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


def _parse_hn_location(comment_text: str) -> str:
    """Extract a free-form location string from an HN job comment.

    Returns the contents of the first ``Location:``/``Where:`` line if
    found; otherwise scans the first ~200 characters for any known country
    keyword and falls back to that snippet, or the empty string.
    """
    text = comment_text or ""
    match = _HN_LOCATION_RE.search(text)
    if match:
        return match.group(1).strip()[:120]

    snippet = text[:200]
    if _infer_country(snippet) not in ("", "Unknown", snippet.strip() or "Unknown"):
        return snippet.strip()[:120]
    return ""


# ---------------------------------------------------------------------------
# Source: Remotive.io
# ---------------------------------------------------------------------------

def search_remotive(keywords: list[str]) -> list[dict]:
    """Search Remotive.io (JSON API, no auth required) for remote tech jobs."""
    query = " ".join(keywords[:5])
    url = "https://remotive.com/api/remote-jobs"
    jobs = []

    try:
        response = _get(url, params={"search": query, "limit": 50})
        data = response.json()
        for job in data.get("jobs", []):
            location = job.get("candidate_required_location", "")
            jobs.append(
                {
                    "title": job.get("title", ""),
                    "company": job.get("company_name", ""),
                    "location": location or "Remote",
                    "country": _infer_country(location),
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


# ---------------------------------------------------------------------------
# Source: Hacker News "Who is Hiring?" thread
# ---------------------------------------------------------------------------

def search_hn_who_is_hiring(keywords: list[str]) -> list[dict]:
    """Scrape the Hacker News 'Who is Hiring?' thread via Algolia HN API.

    Each comment is parsed for a ``Location:`` line so HN jobs now ship with
    a real ``country`` rather than a hardcoded ``Unknown``.
    """
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
            parsed_location = _parse_hn_location(text)
            location = parsed_location or "Remote / Unknown"
            country = _infer_country(parsed_location) if parsed_location else "Unknown"

            jobs.append(
                {
                    "title": "Software Engineer (HN)",
                    "company": "Unknown",
                    "location": location,
                    "country": country,
                    "description": text[:2000],
                    "url": f"https://news.ycombinator.com/item?id={comment.get('objectID')}",
                    "source": "hackernews",
                    "category": "",
                }
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_search] HN search failed: {exc}", file=sys.stderr)

    return jobs


# ---------------------------------------------------------------------------
# Source: Arbeitnow.com
# ---------------------------------------------------------------------------

def search_arbeitnow(keywords: list[str]) -> list[dict]:
    """Search Arbeitnow.com (free JSON API, EU-heavy job board).

    Arbeitnow's public API doesn't expose a server-side search parameter, so
    we fetch the first page (~100 jobs) and keep only those whose title,
    description, or tags match one of the candidate's top keywords.
    """
    url = "https://www.arbeitnow.com/api/job-board-api"
    jobs: list[dict] = []
    keyword_set = {k.lower() for k in keywords[:10] if k}

    try:
        response = _get(url)
        data = response.json()
        for job in data.get("data", []):
            tags = job.get("tags", []) or []
            text_blob = (
                f"{job.get('title', '')} "
                f"{job.get('description', '')} "
                f"{' '.join(tags)}"
            ).lower()
            if keyword_set and not any(k in text_blob for k in keyword_set):
                continue

            location = job.get("location", "") or (
                "Remote" if job.get("remote") else ""
            )
            jobs.append(
                {
                    "title": job.get("title", ""),
                    "company": job.get("company_name", ""),
                    "location": location or "Unknown",
                    "country": _infer_country(location),
                    "description": BeautifulSoup(
                        job.get("description", ""), "html.parser"
                    ).get_text(separator=" "),
                    "url": job.get("url", ""),
                    "source": "arbeitnow",
                    "category": ", ".join(tags[:3]),
                }
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_search] Arbeitnow search failed: {exc}", file=sys.stderr)

    return jobs


# ---------------------------------------------------------------------------
# Source: RemoteOK
# ---------------------------------------------------------------------------

def search_remoteok(keywords: list[str]) -> list[dict]:
    """Search RemoteOK (free JSON API; first array element is metadata)."""
    url = "https://remoteok.com/api"
    jobs: list[dict] = []
    keyword_set = {k.lower() for k in keywords[:10] if k}

    try:
        response = _get(url)
        data = response.json()
        if not isinstance(data, list):
            return jobs
        # Skip the first element which is RemoteOK's metadata/legal banner.
        for job in data[1:]:
            if not isinstance(job, dict):
                continue
            tags = job.get("tags", []) or []
            text_blob = (
                f"{job.get('position', '')} "
                f"{job.get('description', '')} "
                f"{' '.join(tags)}"
            ).lower()
            if keyword_set and not any(k in text_blob for k in keyword_set):
                continue

            location = job.get("location", "") or "Worldwide"
            jobs.append(
                {
                    "title": job.get("position", ""),
                    "company": job.get("company", ""),
                    "location": location,
                    "country": _infer_country(location),
                    "description": BeautifulSoup(
                        job.get("description", ""), "html.parser"
                    ).get_text(separator=" "),
                    "url": job.get("url") or job.get("apply_url", ""),
                    "source": "remoteok",
                    "category": ", ".join(tags[:3]),
                }
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[job_search] RemoteOK search failed: {exc}", file=sys.stderr)

    return jobs


# ---------------------------------------------------------------------------
# Source: Jobicy
# ---------------------------------------------------------------------------

def search_jobicy(keywords: list[str]) -> list[dict]:
    """Search Jobicy (free JSON API; supports a per-tag query parameter)."""
    url = "https://jobicy.com/api/v2/remote-jobs"
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    # Jobicy is keyed on a single-tag query; cycle through the candidate's
    # top three skills to broaden coverage.
    for keyword in keywords[:3]:
        try:
            response = _get(url, params={"count": 50, "tag": keyword.lower()})
            data = response.json()
            for job in data.get("jobs", []):
                job_id = str(job.get("id", ""))
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                location = job.get("jobGeo", "") or ""
                industries = job.get("jobIndustry", []) or []
                jobs.append(
                    {
                        "title": job.get("jobTitle", ""),
                        "company": job.get("companyName", ""),
                        "location": location or "Remote",
                        "country": _infer_country(location),
                        "description": BeautifulSoup(
                            job.get("jobDescription", "") or job.get("jobExcerpt", ""),
                            "html.parser",
                        ).get_text(separator=" "),
                        "url": job.get("url", ""),
                        "source": "jobicy",
                        "category": ", ".join(map(str, industries[:3])),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            print(
                f"[job_search] Jobicy search failed for tag {keyword!r}: {exc}",
                file=sys.stderr,
            )

    return jobs


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

# List of source function *names* (looked up at call time so unit tests can
# patch the individual functions on this module).
_SEARCH_SOURCE_NAMES: tuple[str, ...] = (
    "search_remotive",
    "search_hn_who_is_hiring",
    "search_arbeitnow",
    "search_remoteok",
    "search_jobicy",
)


def _resolve_sources() -> list[Callable[[list[str]], list[dict]]]:
    """Return the active search-source callables, resolved fresh every call."""
    module = sys.modules[__name__]
    return [getattr(module, name) for name in _SEARCH_SOURCE_NAMES]


def _parse_country_filter(raw: str) -> list[str]:
    """Split the COUNTRY config value into a list of lowercase OR-terms."""
    return [term.strip().lower() for term in (raw or "").split(",") if term.strip()]


def _matches_country_filter(job: dict, filter_terms: list[str]) -> bool:
    """Return True if the job matches *any* of the supplied filter terms."""
    if not filter_terms:
        return True
    haystack = (
        f"{job.get('country', '')} {job.get('location', '')}".lower()
    )
    return any(term in haystack for term in filter_terms)


def search_jobs(profile: dict) -> list[dict]:
    """Run every registered job source and return a deduplicated, filtered list."""
    skills = profile.get("skills", [])
    if not skills:
        raise ValueError("Profile contains no skills to search with")

    keywords = skills[:10]
    print(f"[job_search] Searching with keywords: {keywords}")

    filter_terms = _parse_country_filter(getattr(config, "COUNTRY", ""))
    if filter_terms:
        print(f"[job_search] Filtering by country/region terms: {filter_terms!r}")

    all_jobs: list[dict] = []
    for name, source_fn in zip(_SEARCH_SOURCE_NAMES, _resolve_sources()):
        try:
            source_jobs = source_fn(keywords)
        except Exception as exc:  # noqa: BLE001 – be resilient to bad sources
            print(f"[job_search] Source {name} crashed: {exc}", file=sys.stderr)
            continue
        print(f"[job_search]   {name}: {len(source_jobs)} jobs")
        all_jobs.extend(source_jobs)

    if filter_terms:
        before = len(all_jobs)
        all_jobs = [job for job in all_jobs if _matches_country_filter(job, filter_terms)]
        print(
            f"[job_search] Country filter: {before} → {len(all_jobs)} jobs"
        )

    # Deduplicate by URL (keep first occurrence; jobs without URL are kept as-is).
    seen_urls: set[str] = set()
    unique_jobs: list[dict] = []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
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

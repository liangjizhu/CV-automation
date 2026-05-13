"""Evaluate job descriptions against a candidate profile using an LLM."""

import json
import os
import sys
import time

from openai import OpenAI

import config

PROFILE_PATH = os.path.join("data", "profile.json")
JOBS_RAW_PATH = os.path.join("data", "jobs_raw.json")
JOBS_SCORED_PATH = os.path.join("data", "jobs_scored.json")
SCORE_CACHE_PATH = os.path.join("data", "scored_cache.json")

_DELAY_BETWEEN_CALLS = 1  # seconds – respect rate limits
_MAX_DESC_CHARS = 3000  # truncate long descriptions to save tokens

_CACHE_FIELDS = ("score", "classification", "reasoning")


def _load_score_cache(cache_path: str = SCORE_CACHE_PATH) -> dict:
    """Load the URL→evaluation cache, returning an empty dict on any error."""
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[evaluate_jobs] Cache at {cache_path} unreadable ({exc}); starting empty.",
            file=sys.stderr,
        )
        return {}


def _save_score_cache(cache: dict, cache_path: str = SCORE_CACHE_PATH) -> None:
    """Persist the URL→evaluation cache to disk."""
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=2, ensure_ascii=False)


def _build_evaluation_prompt(profile: dict, job: dict) -> str:
    """Build the LLM prompt for evaluating a single job."""
    skills = ", ".join(profile.get("skills", []))
    summary = profile.get("summary", "")
    description = job.get("description", "")[:_MAX_DESC_CHARS]
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")

    return (
        "You are an expert job-fit evaluator.\n"
        "Given a candidate profile and a job description, respond with a JSON object "
        "containing:\n"
        "  - score (integer 1-10, where 10 is a perfect fit)\n"
        "  - classification (one of: 'research', 'industry')\n"
        "  - reasoning (string, 1-2 sentences explaining the score)\n\n"
        "Return ONLY valid JSON with no markdown fences.\n\n"
        f"Candidate skills: {skills}\n"
        f"Candidate summary: {summary}\n\n"
        f"Job title: {title}\n"
        f"Company: {company}\n"
        f"Job description:\n{description}"
    )


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from an LLM response."""
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def evaluate_job(profile: dict, job: dict, client: OpenAI) -> dict:
    """Evaluate a single job and return the job dict enriched with LLM scores."""
    prompt = _build_evaluation_prompt(profile, job)

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned no content (content was None)")
        raw = _strip_code_fences(content.strip())
        evaluation = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"[evaluate_jobs] JSON parse error for '{job.get('title')}': {exc}",
            file=sys.stderr,
        )
        evaluation = {"score": 0, "classification": "unknown", "reasoning": "Parse error"}
    except Exception as exc:  # noqa: BLE001
        print(
            f"[evaluate_jobs] LLM error for '{job.get('title')}': {exc}",
            file=sys.stderr,
        )
        evaluation = {"score": 0, "classification": "unknown", "reasoning": str(exc)}

    enriched = {**job, **evaluation}
    return enriched


def evaluate_jobs(
    profile_path: str = PROFILE_PATH,
    jobs_raw_path: str = JOBS_RAW_PATH,
) -> list[dict]:
    """Load profile and raw jobs, evaluate each, save scored jobs, and return them.

    When ``OPENAI_API_KEY`` is not set the function degrades gracefully: all
    jobs are returned with a default score of 0 and classification ``"unscored"``
    so that the rest of the pipeline can still produce output artefacts.
    """
    api_key = config.LLM_API_KEY

    for path in (profile_path, jobs_raw_path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Required file not found: {path}")

    with open(profile_path, encoding="utf-8") as fh:
        profile = json.load(fh)

    with open(jobs_raw_path, encoding="utf-8") as fh:
        jobs = json.load(fh)

    if not jobs:
        print("[evaluate_jobs] No jobs to evaluate.")
        return []

    if not api_key:
        print(
            "[evaluate_jobs] WARNING: LLM_API_KEY is not set. "
            "Skipping LLM scoring; all jobs will receive a default score of 0."
        )
        scored_jobs = [
            {
                **job,
                "score": 0,
                "classification": "unscored",
                "reasoning": "LLM_API_KEY not configured – LLM scoring was skipped.",
            }
            for job in jobs
        ]
        os.makedirs("data", exist_ok=True)
        with open(JOBS_SCORED_PATH, "w", encoding="utf-8") as fh:
            json.dump(scored_jobs, fh, indent=2, ensure_ascii=False)
        print(f"[evaluate_jobs] Default-scored jobs saved to {JOBS_SCORED_PATH}")
        return scored_jobs

    cache = _load_score_cache(SCORE_CACHE_PATH)
    scored_jobs: list[dict] = []
    cache_hits = 0
    new_evaluations = 0

    client: OpenAI | None = None  # instantiated lazily once we know we need it

    print(
        f"[evaluate_jobs] Evaluating {len(jobs)} jobs with {config.LLM_MODEL} "
        f"(cache size: {len(cache)}) …"
    )
    for i, job in enumerate(jobs, start=1):
        url = job.get("url", "")
        cached = cache.get(url) if url else None
        if cached and all(field in cached for field in _CACHE_FIELDS):
            scored_jobs.append({**job, **{k: cached[k] for k in _CACHE_FIELDS}})
            cache_hits += 1
            continue

        if client is None:
            client = OpenAI(api_key=api_key, base_url=config.LLM_BASE_URL or None)

        print(
            f"[evaluate_jobs] ({i}/{len(jobs)}) Evaluating: {job.get('title', 'N/A')} "
            f"@ {job.get('company', 'N/A')}"
        )
        scored = evaluate_job(profile, job, client)
        scored_jobs.append(scored)
        new_evaluations += 1

        if url:
            cache[url] = {field: scored.get(field) for field in _CACHE_FIELDS}

        time.sleep(_DELAY_BETWEEN_CALLS)

    os.makedirs("data", exist_ok=True)
    with open(JOBS_SCORED_PATH, "w", encoding="utf-8") as fh:
        json.dump(scored_jobs, fh, indent=2, ensure_ascii=False)
    _save_score_cache(cache, SCORE_CACHE_PATH)

    print(
        f"[evaluate_jobs] Scored {len(scored_jobs)} jobs "
        f"({cache_hits} cache hits, {new_evaluations} new LLM calls). "
        f"Saved to {JOBS_SCORED_PATH}."
    )
    return scored_jobs


if __name__ == "__main__":
    try:
        result = evaluate_jobs()
        print(f"Evaluated {len(result)} jobs")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

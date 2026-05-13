"""Main pipeline orchestrator for the CV-automation job search system.

Pipeline steps
--------------
1. parse_cv      – Extract skills from CV.pdf → data/profile.json
2. job_search    – Search job sites           → data/jobs_raw.json
3. evaluate_jobs – Score jobs via LLM         → data/jobs_scored.json
4. rank_jobs     – Rank & classify jobs
5. report_builder– Build HTML report          → output/report.html
6. email_sender  – Send report via Gmail
"""

import json
import os
import sys
import time

from src.parse_cv import parse_cv
from src.job_search import run as search_jobs
from src.evaluate_jobs import evaluate_jobs
from src.rank_jobs import rank_jobs
from src.report_builder import build_report
from src.email_sender import send_if_new_jobs


def _ensure_output_dirs() -> None:
    """Create output directories so artifact uploads never fail due to missing paths."""
    os.makedirs("data", exist_ok=True)
    os.makedirs("output", exist_ok=True)


def _write_empty_artifacts() -> None:
    """Write minimal placeholder output files.

    Called before early exits so that the CI artifact-upload steps always find
    their expected files, even when the pipeline cannot complete normally.
    """
    _ensure_output_dirs()
    scored_path = os.path.join("data", "jobs_scored.json")
    report_path = os.path.join("output", "report.html")
    if not os.path.exists(scored_path):
        with open(scored_path, "w", encoding="utf-8") as fh:
            json.dump([], fh)
    if not os.path.exists(report_path):
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("<!-- Pipeline did not complete successfully. -->\n")


def run_pipeline() -> None:
    """Execute the full job search pipeline end-to-end."""

    # Guarantee that output directories and placeholder files exist so that
    # CI artifact-upload steps always find their expected paths.
    _write_empty_artifacts()

    # Step 1: Parse CV and extract profile
    print("\n=== Step 1/6: Parsing CV ===")
    try:
        profile = parse_cv()
        print(f"  → Extracted {len(profile.get('skills', []))} skills")
    except Exception as exc:
        print(f"[main] FATAL – parse_cv failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 2: Search for jobs
    print("\n=== Step 2/6: Searching jobs ===")
    try:
        raw_jobs = search_jobs()
        print(f"  → Found {len(raw_jobs)} raw job listings")
    except Exception as exc:
        print(f"[main] FATAL – job_search failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not raw_jobs:
        print("[main] No jobs found – building empty report and exiting.")
        try:
            build_report()
        except Exception:
            pass  # placeholder files already written; non-fatal
        sys.exit(0)

    # Step 3: Evaluate jobs with LLM
    print("\n=== Step 3/6: Evaluating jobs ===")
    try:
        scored_jobs = evaluate_jobs()
        print(f"  → Scored {len(scored_jobs)} jobs")
    except Exception as exc:
        print(f"[main] FATAL – evaluate_jobs failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 4: Rank and classify
    print("\n=== Step 4/6: Ranking jobs ===")
    try:
        ranked = rank_jobs()
        all_jobs = ranked.get("all_jobs", [])
        print(
            f"  → Top job: {all_jobs[0].get('title', 'N/A')} "
            f"(score {all_jobs[0].get('score', 0)}/10)"
            if all_jobs
            else "  → No ranked jobs"
        )
    except Exception as exc:
        print(f"[main] FATAL – rank_jobs failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 5: Build HTML report
    print("\n=== Step 5/6: Building report ===")
    try:
        build_report()
        print("  → Report generated at output/report.html")
    except Exception as exc:
        print(f"[main] FATAL – report_builder failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Step 6: Send email (only when there are jobs we haven't notified about yet)
    print("\n=== Step 6/6: Sending email ===")
    try:
        sent = send_if_new_jobs(scored_jobs)
        if sent:
            print("  → Email sent successfully")
        else:
            print("  → No new jobs since last email; nothing sent")
    except Exception as exc:
        # Email failure is non-fatal; report has already been created
        print(f"[main] WARNING – email_sender failed: {exc}", file=sys.stderr)

    print("\n=== Pipeline complete ===")


def run_loop(
    duration_hours: float = 6.0,
    interval_minutes: float = 60.0,
) -> None:
    """Run the pipeline in a loop until *duration_hours* have elapsed.

    Parameters
    ----------
    duration_hours:
        Total wall-clock hours to keep the loop running.  The loop exits as
        soon as the elapsed time exceeds this value (default: 6 hours).
    interval_minutes:
        Minutes to wait between consecutive pipeline runs (default: 60).
    """
    end_time = time.time() + duration_hours * 3600.0
    iteration = 0

    while time.time() < end_time:
        iteration += 1
        start_ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        print(f"\n{'='*60}")
        print(f"  Loop iteration {iteration}  |  {start_ts}")
        print(f"{'='*60}")

        try:
            run_pipeline()
        except SystemExit as exc:
            # run_pipeline may call sys.exit(1) on fatal errors.  We catch that
            # here so the loop continues to the next iteration rather than
            # terminating the whole process.
            print(
                f"[loop] Pipeline exited with code {exc.code} on iteration {iteration}; "
                "continuing loop.",
                file=sys.stderr,
            )

        remaining = end_time - time.time()
        if remaining <= 0:
            break

        interval_secs = interval_minutes * 60.0
        # Skip sleeping when there's less than 10 % of the interval left —
        # not enough time to run another full iteration anyway.
        if remaining < interval_secs * 0.1:
            break

        sleep_secs = min(interval_secs, remaining)
        next_ts = time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(time.time() + sleep_secs),
        )
        print(
            f"\n[loop] Iteration {iteration} complete. "
            f"Next run at {next_ts} "
            f"({remaining / 3600:.1f}h remaining)."
        )
        try:
            time.sleep(sleep_secs)
        except KeyboardInterrupt:
            print("\n[loop] Interrupted – shutting down gracefully.")
            break

    print(f"\n=== Loop ended after {iteration} iteration(s) ===")


if __name__ == "__main__":
    if os.environ.get("RUN_LOOP", "").lower() in ("1", "true", "yes"):
        _duration = float(os.environ.get("LOOP_DURATION_HOURS", "6"))
        _interval = float(os.environ.get("LOOP_INTERVAL_MINUTES", "60"))
        run_loop(duration_hours=_duration, interval_minutes=_interval)
    else:
        run_pipeline()

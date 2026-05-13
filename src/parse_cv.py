"""Parse CV.pdf and extract skills using an LLM."""

import json
import os
import re
import sys

import pdfplumber
from openai import OpenAI

import config

PROFILE_PATH = os.path.join("data", "profile.json")

# Characters of CV text used as the summary in keyword-based (no-LLM) extraction.
_FALLBACK_SUMMARY_MAX_CHARS = 300

# Common technical skills used for keyword-based extraction when the LLM is unavailable.
_COMMON_SKILLS: list[str] = [
    "Python", "Java", "JavaScript", "TypeScript", "C", "C++", "C#", "Go", "Rust",
    "R", "MATLAB", "Scala", "Kotlin", "Swift", "PHP", "Ruby",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Keras", "scikit-learn",
    "Natural Language Processing", "NLP", "Computer Vision", "Reinforcement Learning",
    "Data Science", "Data Analysis", "Statistics", "Probability",
    "SQL", "PostgreSQL", "MySQL", "SQLite", "NoSQL", "MongoDB", "Redis", "Elasticsearch",
    "Docker", "Kubernetes", "AWS", "GCP", "Azure", "CI/CD", "DevOps",
    "Git", "Linux", "Bash", "Shell", "REST", "API", "GraphQL", "Microservices",
    "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI", "Spring",
    "Pandas", "NumPy", "Matplotlib", "Seaborn", "Jupyter",
    "Agile", "Scrum", "LaTeX",
]


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences from an LLM response.

    Some providers (notably DeepSeek) occasionally wrap JSON in ```json fences
    even when asked not to.  Stripping them keeps json.loads happy.
    """
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file using pdfplumber."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"CV file not found: {pdf_path}")

    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    if not text_parts:
        raise ValueError(f"No text could be extracted from {pdf_path}")

    return "\n".join(text_parts)


def _extract_profile_without_llm(cv_text: str) -> dict:
    """Build a minimal profile from CV text using keyword matching (no LLM required).

    Used as a fallback when ``OPENAI_API_KEY`` is not configured.  The resulting
    profile will have accurate skill keywords but no LLM-generated summary or
    structured education/experience data.
    """
    found_skills: list[str] = []
    text_lower = cv_text.lower()
    for skill in _COMMON_SKILLS:
        # Match whole words / phrases to avoid false positives.
        pattern = r"\b" + re.escape(skill.lower()) + r"\b"
        if re.search(pattern, text_lower):
            found_skills.append(skill)

    return {
        "name": "Unknown",
        "skills": found_skills,
        "experience_years": 0,
        "education": [],
        "languages": [],
        "summary": cv_text[:_FALLBACK_SUMMARY_MAX_CHARS].strip(),
    }


def extract_skills_with_llm(cv_text: str, client: OpenAI) -> dict:
    """Use an LLM to extract structured skills and profile from CV text."""
    prompt = (
        "You are a professional CV analyzer. "
        "Given the following CV text, extract a structured profile as JSON with these fields:\n"
        "  - name (string)\n"
        "  - skills (list of strings)\n"
        "  - experience_years (number, your best estimate)\n"
        "  - education (list of strings)\n"
        "  - languages (list of strings)\n"
        "  - summary (string, 2-3 sentences)\n\n"
        "Return ONLY valid JSON with no markdown fences.\n\n"
        f"CV text:\n{cv_text}"
    )

    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    content = response.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned no content (content was None)")
    raw = _strip_code_fences(content.strip())

    try:
        profile = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {raw}") from exc

    return profile


def parse_cv(cv_path: str = config.CV_PATH) -> dict:
    """Full parse pipeline: read PDF → extract skills via LLM → save profile.

    When ``OPENAI_API_KEY`` is not set the function falls back in order:
    1. Load an existing ``data/profile.json`` if one is already present.
    2. Extract text from the PDF and use keyword matching to build a minimal
       profile (no network call required).

    Returns the profile dict.
    """
    api_key = config.LLM_API_KEY
    if not api_key:
        # Fallback 1: reuse a previously saved profile.
        if os.path.exists(PROFILE_PATH):
            print(
                f"[parse_cv] LLM_API_KEY not set; loading existing profile from {PROFILE_PATH}"
            )
            with open(PROFILE_PATH, encoding="utf-8") as fh:
                return json.load(fh)

        # Fallback 2: keyword extraction from the PDF (no LLM).
        print(
            "[parse_cv] WARNING: LLM_API_KEY is not set. "
            "Falling back to keyword-based skill extraction."
        )
        cv_text = extract_text_from_pdf(cv_path)
        profile = _extract_profile_without_llm(cv_text)
        os.makedirs("data", exist_ok=True)
        with open(PROFILE_PATH, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2, ensure_ascii=False)
        print(f"[parse_cv] Keyword-based profile saved to {PROFILE_PATH}")
        return profile

    client = OpenAI(api_key=api_key, base_url=config.LLM_BASE_URL or None)

    print(f"[parse_cv] Extracting text from {cv_path} …")
    cv_text = extract_text_from_pdf(cv_path)

    print(f"[parse_cv] Extracting skills with LLM ({config.LLM_MODEL}) …")
    profile = extract_skills_with_llm(cv_text, client)

    os.makedirs("data", exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)

    print(f"[parse_cv] Profile saved to {PROFILE_PATH}")
    return profile


if __name__ == "__main__":
    try:
        result = parse_cv()
        print(json.dumps(result, indent=2))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

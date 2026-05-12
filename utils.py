# utils.py — shared helpers used by all four architectures

import csv
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config import (
    DATA_DIR,
    DEATH_TERMS,
    EXCLUSION_TERMS,
    HEADERS,
    IV_LOCATIONS,
    LOCATION_CAP,
    OCCUPATIONAL_TERMS,
    PRIMARY_HEAT_TERMS,
    RELEVANCE_THRESHOLD,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    SECONDARY_HEAT_TERMS,
    WEIGHTS,
)

# ── CSV schema ────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "article_id",       # md5 of url
    "url",
    "title",
    "source",
    "published_date",
    "retrieved_date",
    "score",            # rule-based score (None for LLM arm)
    "relevant",         # bool
    "confidence",       # 0.0–1.0 (rule-based: score/100 clamped; LLM: Claude output)
    "heat_terms_found",
    "incident_type",    # death | hospitalization | illness | warning | general | none
    "is_occupational",
    "location_specificity",  # city | county | regional | none
    "summary",
    "architecture",     # rss | headless | llm | alerts
    "full_text_fetched",  # bool — did we retrieve full article?
]


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Rule-based scoring ────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return text.lower()


def score_article(title: str, body: str = "") -> dict:
    """
    Apply keyword scoring rules. Returns a result dict compatible with CSV_FIELDS.
    Used by the RSS arm, headless arm, and alerts arm.
    """
    t = _normalize(title)
    b = _normalize(body)
    full = t + " " + b

    score = 0
    heat_terms_found = []
    is_occupational = False
    incident_type = "none"

    # Exclusions first
    for term in EXCLUSION_TERMS:
        if term in full:
            score += WEIGHTS["exclusion_penalty"]

    # Primary heat terms
    for term in PRIMARY_HEAT_TERMS:
        if term in t:
            score += WEIGHTS["primary_heat_title"]
            if term not in heat_terms_found:
                heat_terms_found.append(term)
        elif term in b:
            score += WEIGHTS["primary_heat_body"]
            if term not in heat_terms_found:
                heat_terms_found.append(term)

    # Title boost if any heat term in title
    if any(term in t for term in PRIMARY_HEAT_TERMS + SECONDARY_HEAT_TERMS):
        score += WEIGHTS["title_boost"]

    # Death co-occurrence bonus
    has_heat = bool(heat_terms_found)
    has_death = any(term in full for term in DEATH_TERMS)
    if has_heat and has_death:
        score += WEIGHTS["death_co_occurrence"]
        incident_type = "death"

    # Secondary heat terms
    for term in SECONDARY_HEAT_TERMS:
        if term in full and term not in heat_terms_found:
            score += WEIGHTS["secondary_heat_term"]
            heat_terms_found.append(term)

    # Occupational
    for term in OCCUPATIONAL_TERMS:
        if term in full:
            score += WEIGHTS["occupational_term"]
            is_occupational = True
            break

    # Location (capped)
    loc_score = 0
    location_specificity = "none"
    for loc in IV_LOCATIONS:
        if loc in full:
            loc_score += WEIGHTS["location_match"]
            if loc in ["el centro", "brawley", "calexico", "holtville",
                       "westmorland", "niland", "calipatria", "seeley",
                       "imperial", "bard", "winterhaven", "ocotillo"]:
                location_specificity = "city"
            elif location_specificity != "city":
                location_specificity = "county"
    score += min(loc_score, LOCATION_CAP)

    # Death terms (standalone)
    if has_death and incident_type == "none":
        score += WEIGHTS["death_term"]

    # Derive incident type if not already set
    if incident_type == "none" and heat_terms_found:
        if any(t in full for t in ["hospitali", "hospital", "er visit", "emergency room"]):
            incident_type = "hospitalization"
        elif any(t in full for t in ["warning", "watch", "advisory", "aviso"]):
            incident_type = "warning"
        else:
            incident_type = "illness"

    relevant = score >= RELEVANCE_THRESHOLD
    confidence = min(round(score / 60.0, 3), 1.0)

    return {
        "score": score,
        "relevant": relevant,
        "confidence": confidence,
        "heat_terms_found": "|".join(heat_terms_found),
        "incident_type": incident_type,
        "is_occupational": is_occupational,
        "location_specificity": location_specificity,
        "summary": "",
        "full_text_fetched": bool(body),
    }


# ── CSV I/O ───────────────────────────────────────────────────────────────────

def load_existing_ids(filepath: str) -> set:
    """Return set of article_ids already in the CSV (for deduplication)."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["article_id"] for row in reader}


def append_articles(filepath: str, articles: list[dict]) -> int:
    """
    Append new articles to CSV, skipping duplicates by article_id.
    Returns count of newly written rows.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    existing = load_existing_ids(filepath)
    new_articles = [a for a in articles if a["article_id"] not in existing]

    if not new_articles:
        return 0

    write_header = not os.path.exists(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for article in new_articles:
            writer.writerow({k: article.get(k, "") for k in CSV_FIELDS})

    return len(new_articles)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def polite_get(url: str, delay: float = REQUEST_DELAY) -> Optional[requests.Response]:
    """GET with polite delay and shared headers. Returns None on failure."""
    time.sleep(delay)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        print(f"  [warn] GET failed for {url}: {e}")
        return None


def fetch_article_text(url: str) -> str:
    """
    Fetch and extract clean article text using trafilatura.
    Returns empty string on failure.
    """
    try:
        import trafilatura
        resp = polite_get(url)
        if resp is None:
            return ""
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        return text or ""
    except Exception as e:
        print(f"  [warn] trafilatura failed for {url}: {e}")
        return ""

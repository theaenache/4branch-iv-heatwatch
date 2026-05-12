#!/usr/bin/env python3
"""
arch_llm.py — Architecture 3: Sitemap discovery + full article fetch + Claude

Discovery:  TownNews news sitemaps (IV Press, Desert Review) — complete daily index
            KYMA Imperial County RSS (sitemap is JS-protected)
            Google News RSS search — broad sweep across all indexed sources
Fetch:      trafilatura full article text
Classify:   Claude Sonnet — structured JSON extraction
Output:     llm_scored.csv
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import anthropic
import feedparser
import requests

from config import (
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
    ARTICLE_CHAR_LIMIT,
    GOOGLE_NEWS_QUERIES,
    HEADERS,
    IV_LOCATIONS,
    KYMA_RSS,
    LLM_OUTPUT,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    SITEMAP_SOURCES,
    PRIMARY_HEAT_TERMS,
    SECONDARY_HEAT_TERMS,
)
from utils import append_articles, fetch_article_text, make_id, now_iso, polite_get

# Only process articles published within this window
LOOKBACK_HOURS = 26  # slightly over 24h to catch any timezone edge cases

# Light pre-filter before sending to Claude (saves API cost on obvious non-matches)
PREFILTER_TERMS = (
    PRIMARY_HEAT_TERMS
    + SECONDARY_HEAT_TERMS
    + ["heat", "calor", "hyperthermia", "coroner", "death", "muerte", "died"]
)


# ── Claude prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a public health surveillance assistant monitoring Imperial Valley, California
for heat-related illness news. Imperial Valley includes: El Centro, Brawley, Calexico, Holtville,
Imperial, Westmorland, Niland, Calipatria, Seeley, Bard, Winterhaven, and Ocotillo.

You will receive a news article. Analyze it and respond ONLY with a valid JSON object — no preamble,
no markdown, no explanation. Use exactly these fields:

{
  "relevant": true or false,
  "confidence": 0.0 to 1.0,
  "heat_terms_found": ["list", "of", "heat-related", "terms", "found"],
  "incident_type": "death" | "hospitalization" | "illness" | "warning" | "general" | "none",
  "is_occupational": true or false,
  "location_specificity": "city" | "county" | "regional" | "none",
  "summary": "one sentence describing the article, or empty string if not relevant",
  "exclude_reason": null or "brief reason why not relevant"
}

An article is relevant if it describes:
- A heat-related illness, injury, or death affecting a person or persons
- An official heat warning or emergency affecting Imperial Valley residents
- Community or public health response to extreme heat in Imperial Valley

An article is NOT relevant if it:
- Is about heat in a different geography (without IV connection)
- Mentions heat only in passing or metaphorically
- Is about heat pumps, heating systems, or sports heat checks"""


def classify_with_claude(client: anthropic.Anthropic, title: str, text: str, url: str) -> dict:
    """Send article to Claude and return parsed classification dict."""
    article_text = f"TITLE: {title}\n\nURL: {url}\n\nARTICLE TEXT:\n{text[:ARTICLE_CHAR_LIMIT]}"

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": article_text}],
        )
        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [warn] Claude JSON parse error for {url}: {e}")
        return {"relevant": False, "confidence": 0.0, "exclude_reason": "parse_error"}
    except anthropic.APIError as e:
        print(f"  [warn] Claude API error for {url}: {e}")
        return {"relevant": False, "confidence": 0.0, "exclude_reason": "api_error"}


def passes_prefilter(title: str, description: str = "") -> bool:
    """Quick keyword check before spending an API call."""
    combined = (title + " " + description).lower()
    return any(term.lower() in combined for term in PREFILTER_TERMS)


def cutoff_dt() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


# ── Sitemap fetching ──────────────────────────────────────────────────────────

SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def fetch_sitemap_articles(source: dict) -> list[dict]:
    """Pull TownNews news sitemap and return candidate article dicts."""
    print(f"  Fetching sitemap: {source['name']}")
    resp = polite_get(source["url"])
    if resp is None:
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"  [warn] Sitemap XML parse error for {source['name']}: {e}")
        return []

    cutoff = cutoff_dt()
    candidates = []

    for url_el in root.findall("sm:url", SITEMAP_NS):
        loc = url_el.findtext("sm:loc", namespaces=SITEMAP_NS) or ""
        if not loc:
            continue

        # Get publication date from news namespace
        pub_date_str = url_el.findtext("news:news/news:publication_date", namespaces=SITEMAP_NS) or ""
        title = url_el.findtext("news:news/news:title", namespaces=SITEMAP_NS) or ""

        # Parse and filter by date
        pub_dt = None
        if pub_date_str:
            try:
                pub_dt = datetime.fromisoformat(pub_date_str)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except ValueError:
                pass  # include if we can't parse the date

        candidates.append({
            "url": loc,
            "title": title,
            "source": source["name"],
            "published_date": pub_date_str,
        })

    print(f"  {source['name']} sitemap: {len(candidates)} articles in lookback window")
    return candidates


# ── RSS fetching (KYMA + Google News) ────────────────────────────────────────

def fetch_rss_candidates(url: str, source_name: str) -> list[dict]:
    """Pull an RSS feed and return candidate dicts (title + url + date)."""
    time.sleep(REQUEST_DELAY)
    feed = feedparser.parse(url, request_headers={"User-Agent": HEADERS["User-Agent"]})

    cutoff = cutoff_dt()
    candidates = []
    for entry in feed.entries:
        link = getattr(entry, "link", "")
        title = getattr(entry, "title", "")
        if not link:
            continue

        pub_date = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
            pub_date = pub_dt.isoformat()

        description = ""
        if hasattr(entry, "summary"):
            description = entry.summary

        candidates.append({
            "url": link,
            "title": title,
            "source": source_name,
            "published_date": pub_date,
            "description": description,
        })

    return candidates


def fetch_google_news_candidates() -> list[dict]:
    """Pull Google News RSS for each search query, deduplicate."""
    print("  Fetching Google News RSS queries...")
    seen = set()
    candidates = []

    for query in GOOGLE_NEWS_QUERIES:
        encoded = query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        batch = fetch_rss_candidates(url, "Google News")
        for c in batch:
            if c["url"] not in seen:
                seen.add(c["url"])
                candidates.append(c)

    print(f"  Google News: {len(candidates)} unique candidates across all queries")
    return candidates


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Architecture 3: LLM agent (sitemap + Claude Sonnet) ===")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[error] ANTHROPIC_API_KEY not set")
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    # 1. Collect candidates from all discovery sources
    candidates = []

    for source in SITEMAP_SOURCES:
        candidates.extend(fetch_sitemap_articles(source))

    print(f"  Fetching KYMA RSS (sitemap JS-protected)...")
    candidates.extend(fetch_rss_candidates(KYMA_RSS, "KYMA"))

    candidates.extend(fetch_google_news_candidates())

    # Deduplicate by URL
    seen_urls = set()
    unique_candidates = []
    for c in candidates:
        if c["url"] not in seen_urls:
            seen_urls.add(c["url"])
            unique_candidates.append(c)

    print(f"\nTotal unique candidates: {len(unique_candidates)}")

    # 2. Pre-filter
    prefiltered = [
        c for c in unique_candidates
        if passes_prefilter(c["title"], c.get("description", ""))
    ]
    print(f"After keyword pre-filter: {len(prefiltered)} candidates sent to Claude")

    # 3. Fetch full text + classify with Claude
    articles = []
    for i, candidate in enumerate(prefiltered, 1):
        url = candidate["url"]
        title = candidate["title"]
        print(f"  [{i}/{len(prefiltered)}] {title[:70]}...")

        full_text = fetch_article_text(url)
        full_text_fetched = bool(full_text)

        if not full_text:
            # Fall back to description if available
            full_text = candidate.get("description", title)

        classification = classify_with_claude(client, title, full_text, url)

        articles.append({
            "article_id": make_id(url),
            "url": url,
            "title": title,
            "source": candidate["source"],
            "published_date": candidate.get("published_date", ""),
            "retrieved_date": now_iso(),
            "score": None,
            "relevant": classification.get("relevant", False),
            "confidence": classification.get("confidence", 0.0),
            "heat_terms_found": "|".join(classification.get("heat_terms_found", [])),
            "incident_type": classification.get("incident_type", "none"),
            "is_occupational": classification.get("is_occupational", False),
            "location_specificity": classification.get("location_specificity", "none"),
            "summary": classification.get("summary", ""),
            "architecture": "llm",
            "full_text_fetched": full_text_fetched,
        })

        time.sleep(0.5)  # light pause between API calls

    written = append_articles(LLM_OUTPUT, articles)
    relevant_new = sum(1 for a in articles if a["relevant"])

    print(f"\nLLM arm complete: {written} new articles written to {LLM_OUTPUT}")
    print(f"  of which relevant: {relevant_new}")
    print(f"  Claude API calls made: {len(prefiltered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

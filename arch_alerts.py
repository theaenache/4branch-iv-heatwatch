#!/usr/bin/env python3
"""
arch_alerts.py — Architecture 4: Google News/Alerts RSS broad sweep

Sources: Google News RSS search queries (same as LLM arm's broad sweep, but
         scored with rule-based keyword matching rather than Claude).
         Represents the "widest net, least source control" architecture.
Output:  alerts_scored.csv
"""

import sys
import time
from datetime import datetime, timezone, timedelta

import feedparser

from config import ALERTS_OUTPUT, GOOGLE_NEWS_QUERIES, HEADERS, REQUEST_DELAY
from utils import append_articles, make_id, now_iso, score_article

LOOKBACK_HOURS = 26


def cutoff_dt() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


def fetch_query(query: str) -> list[dict]:
    """Fetch one Google News RSS query and return scored article dicts."""
    encoded = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

    time.sleep(REQUEST_DELAY)
    feed = feedparser.parse(url, request_headers={"User-Agent": HEADERS["User-Agent"]})

    if feed.bozo and not feed.entries:
        print(f"  [warn] Feed error for query '{query}': {feed.bozo_exception}")
        return []

    cutoff = cutoff_dt()
    articles = []
    for entry in feed.entries:
        link = getattr(entry, "link", "")
        title = getattr(entry, "title", "")
        if not link or not title:
            continue

        # Date filter
        pub_date = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
            pub_date = pub_dt.isoformat()

        body = getattr(entry, "summary", "")
        result = score_article(title, body)

        # Tag the query that surfaced this article
        articles.append({
            "article_id": make_id(link),
            "url": link,
            "title": title,
            "source": f"Google News ({entry.get('source', {}).get('title', 'unknown')})",
            "published_date": pub_date,
            "retrieved_date": now_iso(),
            "architecture": "alerts",
            **result,
        })

    return articles


def main():
    print("=== Architecture 4: Google Alerts RSS broad sweep ===")

    seen_ids = set()
    all_articles = []

    for query in GOOGLE_NEWS_QUERIES:
        print(f"  Query: '{query}'")
        articles = fetch_query(query)

        # Deduplicate within this run
        for a in articles:
            if a["article_id"] not in seen_ids:
                seen_ids.add(a["article_id"])
                all_articles.append(a)

    written = append_articles(ALERTS_OUTPUT, all_articles)
    relevant_new = sum(1 for a in all_articles if a["relevant"])

    print(f"\nAlerts arm complete: {written} new articles written to {ALERTS_OUTPUT}")
    print(f"  of which relevant: {relevant_new}")
    print(f"  unique sources surfaced: {len({a['source'] for a in all_articles})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

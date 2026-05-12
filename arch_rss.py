#!/usr/bin/env python3
"""
arch_rss.py — Architecture 1: RSS feeds + rule-based keyword scoring

Sources: KYMA Imperial County feed, IV Press RSS, Desert Review RSS
Method:  feedparser → score_article() → append to rss_scored.csv
"""

import sys
import time
from datetime import datetime, timezone

import feedparser

from config import HEADERS, REQUEST_DELAY, RSS_OUTPUT, RSS_SOURCES
from utils import append_articles, make_id, now_iso, score_article


def parse_date(entry) -> str:
    """Best-effort ISO date from feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
    return now_iso()


def fetch_feed(source: dict) -> list[dict]:
    """Pull one RSS source and return scored article dicts."""
    time.sleep(REQUEST_DELAY)
    print(f"  Fetching {source['name']} RSS...")

    feed = feedparser.parse(
        source["url"],
        request_headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": HEADERS["Accept"],
        },
    )

    if feed.bozo and not feed.entries:
        print(f"  [warn] {source['name']}: feed parse error — {feed.bozo_exception}")
        return []

    articles = []
    for entry in feed.entries:
        url = getattr(entry, "link", "")
        title = getattr(entry, "title", "")
        if not url or not title:
            continue

        # Use description/summary as body proxy (no full fetch in this arm)
        body = ""
        if hasattr(entry, "summary"):
            body = entry.summary
        elif hasattr(entry, "content"):
            body = " ".join(c.get("value", "") for c in entry.content)

        result = score_article(title, body)

        articles.append({
            "article_id": make_id(url),
            "url": url,
            "title": title,
            "source": source["name"],
            "published_date": parse_date(entry),
            "retrieved_date": now_iso(),
            "architecture": "rss",
            **result,
        })

    relevant = sum(1 for a in articles if a["relevant"])
    print(f"  {source['name']}: {len(articles)} entries, {relevant} relevant")
    return articles


def main():
    print("=== Architecture 1: RSS + keyword scoring ===")
    all_articles = []

    for source in RSS_SOURCES:
        articles = fetch_feed(source)
        all_articles.extend(articles)

    # Write all (relevant and not) so we can audit precision later
    # but flag relevant=False rows so the merge step can filter
    written = append_articles(RSS_OUTPUT, all_articles)
    relevant_new = sum(1 for a in all_articles if a["relevant"])

    print(f"\nRSS arm complete: {written} new articles written to {RSS_OUTPUT}")
    print(f"  of which relevant: {relevant_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

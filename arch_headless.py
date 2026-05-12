#!/usr/bin/env python3
"""
arch_headless.py — Architecture 2: Headless browser scraping

Sources: Calexico Chronicle, Holtville Tribune (captcha-blocked to plain requests),
         + section page sweeps of KYMA and IV Press for articles outside RSS window.
Method:  Playwright (Chromium) → extract article links → trafilatura text →
         rule-based scoring → append to headless_scored.csv
"""

import re
import sys
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

from config import HEADLESS_TARGETS, HEADLESS_OUTPUT, REQUEST_DELAY
from utils import append_articles, fetch_article_text, make_id, now_iso, score_article

# How many articles to process per section page (avoid hammering small outlets)
MAX_ARTICLES_PER_SITE = 30

# Patterns that indicate an article link (vs nav/tag/category pages)
ARTICLE_URL_PATTERNS = [
    r"/\d{4}/\d{2}/\d{2}/",          # date-based WordPress URLs
    r"/article_[a-f0-9\-]+\.html",    # TownNews article pattern
    r"/news/[^/]+/?$",                # generic /news/slug
    r"/local/[^/]+/?$",
    r"/[^/]+-\d+/?$",                 # slug-with-id
]

SKIP_URL_PATTERNS = [
    r"/category/", r"/tag/", r"/author/", r"/page/\d",
    r"/wp-content/", r"/wp-admin/", r"#", r"mailto:",
    r"\.(jpg|jpeg|png|gif|pdf|mp4|mp3)$",
]


def looks_like_article(url: str) -> bool:
    url_lower = url.lower()
    if any(re.search(p, url_lower) for p in SKIP_URL_PATTERNS):
        return False
    if any(re.search(p, url_lower) for p in ARTICLE_URL_PATTERNS):
        return True
    # Fallback: at least 2 path segments and no query string
    parsed = urlparse(url)
    return len([s for s in parsed.path.split("/") if s]) >= 2 and not parsed.query


def scrape_section(page, target: dict) -> list[str]:
    """
    Load a section page with Playwright and extract article URLs.
    Returns list of absolute URLs.
    """
    base = target["base_url"]
    section_url = target["section_url"]

    print(f"  Loading {target['name']} section: {section_url}")
    try:
        page.goto(section_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)  # let JS settle
    except PwTimeout:
        print(f"  [warn] Timeout loading {section_url}")
        return []
    except Exception as e:
        print(f"  [warn] Failed loading {section_url}: {e}")
        return []

    # Extract all hrefs
    hrefs = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.href)"
    )

    # Normalize and filter to same-domain article links
    seen = set()
    article_urls = []
    for href in hrefs:
        href = href.split("#")[0].rstrip("/")
        if not href.startswith("http"):
            href = urljoin(base, href)
        parsed = urlparse(href)
        base_parsed = urlparse(base)
        if parsed.netloc != base_parsed.netloc:
            continue
        if href in seen:
            continue
        if looks_like_article(href):
            seen.add(href)
            article_urls.append(href)

    print(f"  {target['name']}: found {len(article_urls)} candidate article links")
    return article_urls[:MAX_ARTICLES_PER_SITE]


def process_articles(article_urls: list[str], source_name: str) -> list[dict]:
    """Fetch full text and score each article URL."""
    articles = []
    for url in article_urls:
        time.sleep(REQUEST_DELAY)
        text = fetch_article_text(url)
        if not text:
            # Still score on URL/title heuristic if fetch fails
            title = url.split("/")[-1].replace("-", " ").replace("_", " ")
            text = ""
        else:
            # Extract a title-like first line
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            title = lines[0][:200] if lines else url

        result = score_article(title, text)

        articles.append({
            "article_id": make_id(url),
            "url": url,
            "title": title,
            "source": source_name,
            "published_date": "",   # headless arm doesn't reliably get pub dates
            "retrieved_date": now_iso(),
            "architecture": "headless",
            **result,
        })

    return articles


def main():
    print("=== Architecture 2: Headless browser (Playwright) ===")
    all_articles = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        for target in HEADLESS_TARGETS:
            article_urls = scrape_section(page, target)
            if article_urls:
                articles = process_articles(article_urls, target["name"])
                all_articles.extend(articles)
                relevant = sum(1 for a in articles if a["relevant"])
                print(f"  {target['name']}: {len(articles)} scored, {relevant} relevant")

        browser.close()

    written = append_articles(HEADLESS_OUTPUT, all_articles)
    relevant_new = sum(1 for a in all_articles if a["relevant"])

    print(f"\nHeadless arm complete: {written} new articles written to {HEADLESS_OUTPUT}")
    print(f"  of which relevant: {relevant_new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

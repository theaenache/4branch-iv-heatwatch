# IV Heat Scraper — Architecture Comparison

Monitors Imperial Valley news media for heat-related illness coverage during hot season.
Four parallel scraping architectures run daily via GitHub Actions and write to a shared
`master_comparison.csv` so you can evaluate each arm's coverage, precision, and reliability.

## Architectures

| Arm | Discovery method | Classification | Output |
|-----|-----------------|----------------|--------|
| `rss` | RSS feeds (KYMA, IV Press, Desert Review) | Rule-based keyword scoring | `data/rss_scored.csv` |
| `headless` | Playwright section-page crawl (all sites incl. captcha-blocked) | Rule-based keyword scoring | `data/headless_scored.csv` |
| `llm` | TownNews news sitemaps + KYMA RSS + Google News RSS | Claude Sonnet full-article classification | `data/llm_scored.csv` |
| `alerts` | Google News RSS search queries (8 queries, EN + ES) | Rule-based keyword scoring | `data/alerts_scored.csv` |

## Master comparison columns

- `found_by` — pipe-separated list of architectures that caught this article (e.g. `llm|rss`)
- `arch_count` — number of architectures that found it
- `any_relevant` — true if any architecture marked it relevant
- Per-arch: `{arch}_relevant`, `{arch}_score`, `{arch}_confidence`
- `llm_summary` — Claude's one-sentence summary (LLM arm only)
- `best_incident_type` — death | hospitalization | illness | warning | general | none

## Setup

1. Fork or clone this repo
2. Add `ANTHROPIC_API_KEY` as a GitHub Actions secret (Settings → Secrets → Actions)
3. The workflow runs daily at 08:00 PDT. Trigger manually via Actions → workflow_dispatch.

## Local run

```bash
pip install -r requirements.txt
playwright install chromium

ANTHROPIC_API_KEY=sk-... python arch_llm.py
python arch_rss.py
python arch_headless.py
python arch_alerts.py
python merge.py
```

## Sources

- **KYMA** (`kyma.com`) — largest IV TV station, WordPress, Imperial County RSS
- **IV Press** (`ivpressonline.com`) — daily newspaper, TownNews CMS, news sitemap available
- **Desert Review** (`thedesertreview.com`) — TownNews CMS, news sitemap available
- **Calexico Chronicle** — WordPress, SiteGround-protected (headless arm only)
- **Holtville Tribune** — WordPress, SiteGround-protected (headless arm only)
- **Google News** — broad sweep across all indexed sources including the above

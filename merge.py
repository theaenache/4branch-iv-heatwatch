#!/usr/bin/env python3
"""
merge.py — Deduplicate and merge all four architecture CSVs into master_comparison.csv

Each article in the master has a `found_by` column listing which architecture(s)
caught it, making cross-architecture coverage comparison immediate.
"""

import csv
import os
import sys
from collections import defaultdict

from config import (
    ALERTS_OUTPUT,
    DATA_DIR,
    HEADLESS_OUTPUT,
    LLM_OUTPUT,
    MASTER_OUTPUT,
    RSS_OUTPUT,
)

ARCH_FILES = {
    "rss": RSS_OUTPUT,
    "headless": HEADLESS_OUTPUT,
    "llm": LLM_OUTPUT,
    "alerts": ALERTS_OUTPUT,
}

MASTER_FIELDS = [
    "article_id",
    "url",
    "title",
    "source",
    "published_date",
    "retrieved_date",
    "found_by",                 # pipe-separated list of architectures e.g. "rss|llm"
    "arch_count",               # how many architectures caught this article
    "any_relevant",             # true if ANY architecture marked it relevant
    "rss_relevant",
    "rss_score",
    "rss_confidence",
    "headless_relevant",
    "headless_score",
    "headless_confidence",
    "llm_relevant",
    "llm_confidence",
    "llm_summary",
    "alerts_relevant",
    "alerts_score",
    "alerts_confidence",
    "best_incident_type",
    "best_heat_terms",
    "is_occupational",
    "location_specificity",
]


def load_arch_csv(filepath: str) -> dict[str, dict]:
    """Load a per-architecture CSV, keyed by article_id."""
    if not os.path.exists(filepath):
        print(f"  [warn] {filepath} not found — skipping")
        return {}
    with open(filepath, newline="", encoding="utf-8") as f:
        return {row["article_id"]: row for row in csv.DictReader(f)}


def pick_best(rows: list[dict], field: str, prefer_nonempty=True) -> str:
    """Return the first non-empty value for a field across architecture rows."""
    for row in rows:
        val = row.get(field, "")
        if val and val not in ("None", "False", "0", "0.0"):
            return val
    return rows[0].get(field, "") if rows else ""


def main():
    print("=== Merge: building master_comparison.csv ===")

    # Load all four arch CSVs
    arch_data: dict[str, dict[str, dict]] = {}
    for arch, filepath in ARCH_FILES.items():
        arch_data[arch] = load_arch_csv(filepath)
        print(f"  {arch}: {len(arch_data[arch])} total articles loaded")

    # Union of all article_ids
    all_ids: dict[str, list] = defaultdict(list)  # id → list of (arch, row) tuples
    for arch, rows in arch_data.items():
        for article_id, row in rows.items():
            all_ids[article_id].append((arch, row))

    print(f"\nUnique articles across all architectures: {len(all_ids)}")

    # Load existing master to avoid re-writing unchanged rows
    existing_ids = set()
    if os.path.exists(MASTER_OUTPUT):
        with open(MASTER_OUTPUT, newline="", encoding="utf-8") as f:
            existing_ids = {row["article_id"] for row in csv.DictReader(f)}

    os.makedirs(DATA_DIR, exist_ok=True)
    write_header = not os.path.exists(MASTER_OUTPUT)
    new_rows = 0
    updated_rows = 0

    # We rewrite the master completely each run to capture found_by changes
    # (an article found by 1 arch yesterday may now be found by 2)
    tmp_path = MASTER_OUTPUT + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MASTER_FIELDS)
        writer.writeheader()

        for article_id, arch_rows in sorted(all_ids.items()):
            arches = [a for a, _ in arch_rows]
            rows = [r for _, r in arch_rows]

            # Use the richest source for base fields
            # Prefer LLM row (has summary), then others
            llm_row = arch_data["llm"].get(article_id, {})
            rss_row = arch_data["rss"].get(article_id, {})
            hdl_row = arch_data["headless"].get(article_id, {})
            alt_row = arch_data["alerts"].get(article_id, {})

            base_row = llm_row or rss_row or hdl_row or alt_row

            any_relevant = any(
                r.get("relevant", "").lower() in ("true", "1")
                for r in rows
            )

            def relevant_flag(row):
                return row.get("relevant", "False") if row else "False"

            def score_val(row):
                return row.get("score", "") if row else ""

            def conf_val(row):
                return row.get("confidence", "") if row else ""

            master_row = {
                "article_id": article_id,
                "url": base_row.get("url", ""),
                "title": base_row.get("title", ""),
                "source": base_row.get("source", ""),
                "published_date": pick_best(rows, "published_date"),
                "retrieved_date": pick_best(rows, "retrieved_date"),
                "found_by": "|".join(sorted(set(arches))),
                "arch_count": len(set(arches)),
                "any_relevant": any_relevant,
                "rss_relevant": relevant_flag(rss_row),
                "rss_score": score_val(rss_row),
                "rss_confidence": conf_val(rss_row),
                "headless_relevant": relevant_flag(hdl_row),
                "headless_score": score_val(hdl_row),
                "headless_confidence": conf_val(hdl_row),
                "llm_relevant": relevant_flag(llm_row),
                "llm_confidence": conf_val(llm_row),
                "llm_summary": llm_row.get("summary", "") if llm_row else "",
                "alerts_relevant": relevant_flag(alt_row),
                "alerts_score": score_val(alt_row),
                "alerts_confidence": conf_val(alt_row),
                "best_incident_type": pick_best(rows, "incident_type"),
                "best_heat_terms": pick_best(rows, "heat_terms_found"),
                "is_occupational": pick_best(rows, "is_occupational"),
                "location_specificity": pick_best(rows, "location_specificity"),
            }

            writer.writerow(master_row)

            if article_id not in existing_ids:
                new_rows += 1
            else:
                # Check if found_by changed (new arch caught an existing article)
                updated_rows += 1

    # Atomic replace
    os.replace(tmp_path, MASTER_OUTPUT)

    relevant_total = sum(
        1 for rows in all_ids.values()
        if any(r.get("relevant", "").lower() in ("true", "1") for _, r in rows)
    )

    multi_arch = sum(
        1 for rows in all_ids.values()
        if len(set(a for a, _ in rows)) > 1
    )

    print(f"\nMaster CSV written to {MASTER_OUTPUT}")
    print(f"  Total unique articles: {len(all_ids)}")
    print(f"  Relevant by any architecture: {relevant_total}")
    print(f"  Caught by 2+ architectures: {multi_arch}")
    print(f"  New this run: {new_rows}")

    # Print coverage summary
    print("\n--- Coverage by architecture ---")
    for arch in ["rss", "headless", "llm", "alerts"]:
        total = len(arch_data[arch])
        relevant = sum(
            1 for r in arch_data[arch].values()
            if r.get("relevant", "").lower() in ("true", "1")
        )
        print(f"  {arch:10s}: {total:4d} total, {relevant:3d} relevant")

    # Unique catches per architecture (not found by any other)
    print("\n--- Unique catches (not found by other architectures) ---")
    for arch in ["rss", "headless", "llm", "alerts"]:
        unique = sum(
            1 for rows in all_ids.values()
            if set(a for a, _ in rows) == {arch}
            and any(r.get("relevant", "").lower() in ("true", "1") for _, r in rows)
        )
        print(f"  {arch:10s}: {unique} relevant articles found exclusively")

    return 0


if __name__ == "__main__":
    sys.exit(main())

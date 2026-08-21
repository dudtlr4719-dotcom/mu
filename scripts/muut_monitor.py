#!/usr/bin/env python3
"""
MUUT SPOTTED monitor — orchestrates the finder agents (one per source) and
the organizer agent (judges/dedups/writes), then updates index.html.

Runs entirely inside GitHub Actions (github.com's own infra), so pushing the
result back to this repo needs no cross-service credential handoff.
"""
import os
import sys

from common import IMAGES_DIR, load_data, save_data
from finders import (
    finder_google,
    finder_instagram,
    finder_naver_search,
    finder_suwon,
    finder_twitter,
    finder_wesee,
)
from organizer import organize

from datetime import datetime

MIN_ENTRIES = 90  # safety check: repo should already have at least this many

# Trusted/cheap sources first, experimental/Playwright-based ones last — a
# failure in one finder never stops the others (see the try/except below).
FINDERS = [
    finder_suwon,
    finder_wesee,
    finder_naver_search,
    finder_google,
    finder_instagram,
    finder_twitter,
]


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    html, data, m = load_data()
    entries = data["entries"]
    if len(entries) < MIN_ENTRIES:
        print(f"SAFETY ABORT — only {len(entries)} entries parsed, expected >= {MIN_ENTRIES}. No changes made.")
        sys.exit(1)

    existing_ids = {e["id"] for e in entries}
    print(f"Loaded {len(entries)} existing entries. Running finders...")

    all_candidates = []
    for finder in FINDERS:
        label = finder.__name__.rsplit(".", 1)[-1]
        print(f"\n--- {label} ---")
        try:
            found = finder.find(existing_ids)
        except Exception as exc:
            print(f"  finder {label} failed: {exc}")
            found = []
        all_candidates.extend(found)

    print(f"\n{len(all_candidates)} total candidate(s) across all finders. Handing to organizer...\n")
    new_entries = organize(all_candidates, entries)

    data["lastChecked"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if new_entries:
        data["entries"].extend(new_entries)
    save_data(html, data, m)

    print(f"\n=== Summary: {len(new_entries)} new mention(s) added ===")
    for e in new_entries:
        print(f"  + {e['name']} — {e['product']} ({e['source']}) {e['url']}")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"new_count={len(new_entries)}\n")
            summary = "; ".join(f"{e['name']} ({e['product']}, {e['source']})" for e in new_entries)
            f.write(f"new_summary={summary}\n")


if __name__ == "__main__":
    main()

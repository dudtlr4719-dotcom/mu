"""Finder: Instagram (best-effort, unauthenticated).

Instagram gates almost all content behind a login wall for logged-out
visitors, including hashtag/tag pages. Without a logged-in session (which
would mean storing account credentials as a GitHub secret — not done here),
this finder will very likely find nothing on most days. It's still worth
running because Instagram occasionally serves a partial page before
redirecting, and this is where that gets picked up if so.

Every run logs plainly whether it hit the login wall or something else, so a
long streak of "blocked" isn't mistaken for "nothing new happened."
"""
import hashlib
import re

from common import fetch_text

SOURCE_LABEL = "Instagram"
HASHTAG_URLS = [
    "https://www.instagram.com/explore/tags/muut/",
    "https://www.instagram.com/explore/tags/뭍/",
]


def _make_id(url):
    return "instagram-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def find(existing_ids):
    candidates = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [instagram] playwright not installed, skipping this finder")
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            for url in HASHTAG_URLS:
                try:
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                except Exception as exc:
                    print(f"  [instagram] navigation failed for {url}: {exc}")
                    continue

                current_url = page.url
                content = page.content()
                if "/accounts/login" in current_url or "login" in content.lower()[:3000]:
                    print(f"  [instagram] {url}: hit the login wall (expected — no logged-in session)")
                    continue

                post_links = page.eval_on_selector_all(
                    "a[href*='/p/']", "els => els.map(e => e.href)"
                )
                if not post_links:
                    print(f"  [instagram] {url}: page loaded but no post links found")
                    continue

                print(f"  [instagram] {url}: {len(post_links)} post link(s) found, unusual — inspecting")
                for post_url in post_links[:10]:
                    eid = _make_id(post_url)
                    if eid in existing_ids:
                        continue
                    try:
                        html = fetch_text(post_url)
                    except Exception as exc:
                        print(f"  [instagram] fetch failed ({post_url}): {exc}")
                        continue
                    title_m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
                    title = title_m.group(1) if title_m else ""
                    candidates.append(
                        {
                            "id": eid,
                            "url": post_url,
                            "source_label": SOURCE_LABEL,
                            "note": "Instagram에서 발견된 게시물",
                            "needs_judgment": True,
                            "title": title,
                            "post_html": html,
                        }
                    )
            browser.close()
    except Exception as exc:
        print(f"  [instagram] finder failed entirely (browser launch/setup): {exc}")
        return []

    if not candidates:
        print("  [instagram] 0 candidates this run (login wall expected without a signed-in session)")
    return candidates

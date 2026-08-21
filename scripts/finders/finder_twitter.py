"""Finder: Twitter/X (best-effort, unauthenticated), with a Nitter fallback.

X has required a login to view search results since 2023, so the primary
x.com search attempt below will almost always hit a login wall — logged
plainly, not treated as an error. As a fallback this also tries a couple of
public Nitter mirrors (open-source X frontends that don't require login),
but Nitter instances are notoriously unstable and frequently offline; a
failure there is expected background noise, not a sign anything broke.
"""
import hashlib
import re
import urllib.parse

from common import fetch_text

SOURCE_LABEL = "Twitter/X"
QUERIES = ["MUUT 뭍 선글라스", "MUUT eyewear"]
NITTER_MIRRORS = ["https://nitter.net", "https://nitter.poast.org"]


def _make_id(key):
    return "twitter-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _try_x_search(existing_ids):
    candidates = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [twitter] playwright not installed, skipping x.com attempt")
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            for query in QUERIES:
                url = "https://x.com/search?" + urllib.parse.urlencode({"q": query, "f": "live"})
                try:
                    page.goto(url, timeout=20000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                except Exception as exc:
                    print(f"  [twitter] x.com navigation failed for {query!r}: {exc}")
                    continue
                content = page.content()
                if "login" in page.url.lower() or "log in" in content.lower()[:3000]:
                    print(f"  [twitter] x.com: hit the login wall for {query!r} (expected since 2023)")
                    continue
                print(f"  [twitter] x.com: page rendered without a login wall for {query!r}, unusual — "
                      f"but tweet-scraping isn't implemented, flagging for manual follow-up")
            browser.close()
    except Exception as exc:
        print(f"  [twitter] x.com attempt failed entirely: {exc}")
    return candidates


def _try_nitter(existing_ids):
    candidates = []
    for mirror in NITTER_MIRRORS:
        for query in QUERIES:
            search_url = f"{mirror}/search?" + urllib.parse.urlencode({"q": query, "f": "tweets"})
            try:
                html = fetch_text(search_url)
            except Exception as exc:
                print(f"  [twitter] nitter mirror {mirror} unreachable: {exc}")
                continue
            tweet_links = set(re.findall(r'href="(/[^/"]+/status/\d+)"', html))
            if not tweet_links:
                print(f"  [twitter] nitter {mirror}: 0 results for {query!r}")
                continue
            for path in list(tweet_links)[:10]:
                tweet_url = f"{mirror}{path}"
                eid = _make_id(path)
                if eid in existing_ids:
                    continue
                try:
                    tweet_html = fetch_text(tweet_url)
                except Exception as exc:
                    print(f"  [twitter] fetch failed ({tweet_url}): {exc}")
                    continue
                title_m = re.search(r'<meta property="og:description" content="([^"]*)"', tweet_html)
                title = title_m.group(1) if title_m else ""
                candidates.append(
                    {
                        "id": eid,
                        "url": f"https://x.com{path}",
                        "source_label": SOURCE_LABEL,
                        "note": "Twitter/X에서 발견된 게시물 (Nitter 경유)",
                        "needs_judgment": True,
                        "title": title,
                        "post_html": tweet_html,
                    }
                )
                print(f"  [twitter] candidate for AI judgment — {title!r} ({tweet_url})")
        if candidates:
            break  # a working mirror was found, no need to try the rest
    return candidates


def find(existing_ids):
    candidates = []
    candidates.extend(_try_x_search(existing_ids))
    candidates.extend(_try_nitter(existing_ids))
    if not candidates:
        print("  [twitter] 0 candidates this run (x.com login wall + nitter mirrors both expected to be unreliable)")
    return candidates

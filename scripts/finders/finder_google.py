"""Finder: Google search.

Google's search results require JS to render (plain curl gets a
"noscript, please enable JS" redirect page), so this finder uses Playwright's
headless Chromium just to load the results page and collect links. Each
individual result page is then fetched with a plain HTTP request (much
cheaper than another browser page) for the organizer to judge.

Best-effort: Google is known to rate-limit/CAPTCHA datacenter IPs (which is
what GitHub Actions runners are), so this finder may come back empty on any
given day even when nothing is technically wrong. That's logged clearly
rather than treated as an error.
"""
import hashlib
import re
import urllib.parse

from common import fetch_text, generic_image_url, parse_generic_date

SOURCE_LABEL = "Google 검색"
QUERIES = ["MUUT 뭍 선글라스 착용 셀럽", "MUUT eyewear celebrity spotted"]
SKIP_DOMAINS = ("google.", "naver.com", "youtube.com", "instagram.com", "twitter.com", "x.com")


def _make_id(url):
    return "google-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _collect_result_links(page, query):
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "ko", "num": "20"})
    page.goto(url, timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    if "did not match any documents" in page.content().lower():
        return []
    hrefs = page.eval_on_selector_all("a[href^='http']", "els => els.map(e => e.href)")
    return hrefs


def find(existing_ids):
    candidates = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [google] playwright not installed, skipping this finder")
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            seen_urls = set()
            for query in QUERIES:
                try:
                    hrefs = _collect_result_links(page, query)
                except Exception as exc:
                    print(f"  [google] search failed for {query!r}: {exc}")
                    continue
                if not hrefs:
                    print(f"  [google] no results parsed for {query!r} (likely blocked/CAPTCHA)")
                seen_urls.update(hrefs)
            browser.close()
    except Exception as exc:
        print(f"  [google] finder failed entirely (browser launch/setup): {exc}")
        return []

    for url in seen_urls:
        domain = urllib.parse.urlparse(url).netloc.lower()
        if any(skip in domain for skip in SKIP_DOMAINS):
            continue
        eid = _make_id(url)
        if eid in existing_ids:
            continue
        try:
            html = fetch_text(url)
        except Exception as exc:
            print(f"  [google] fetch failed ({url}): {exc}")
            continue
        title_m = re.search(r'<meta property="og:title" content="([^"]*)"', html) or re.search(
            r"<title>([^<]*)</title>", html
        )
        title = title_m.group(1) if title_m else ""
        if "muut" not in html.lower() and "뭍" not in html:
            continue
        candidates.append(
            {
                "id": eid,
                "url": url,
                "source_label": SOURCE_LABEL,
                "note": "Google 검색으로 발견된 게시물",
                "needs_judgment": True,
                "title": title,
                "post_html": html,
            }
        )
        print(f"  [google] candidate for AI judgment — {title!r} ({url})")

    if not candidates:
        print("  [google] 0 candidates this run")
    return candidates

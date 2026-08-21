"""Finder: Google search, via the Custom Search JSON API.

Plain curl gets a "please enable JS" redirect from google.com/search, and
even Playwright-rendered scraping got blocked/CAPTCHA'd running from GitHub
Actions' datacenter IPs (confirmed empirically). The official Custom Search
API sidesteps both problems — it's a normal authenticated REST call, no
rendering or IP reputation involved. Free tier: 100 queries/day.

Needs two secrets: GOOGLE_API_KEY and GOOGLE_CSE_ID (a Programmable Search
Engine configured to search the entire web). Without them, this finder logs
a warning once and returns no candidates rather than failing the run.
"""
import hashlib
import json
import os
import re
import urllib.parse

from common import fetch_text

SOURCE_LABEL = "Google 검색"
QUERIES = ["MUUT 뭍 선글라스 착용", "MUUT eyewear celebrity"]
SKIP_DOMAINS = ("google.", "naver.com", "youtube.com", "instagram.com", "twitter.com", "x.com")


def _make_id(url):
    return "google-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def find(existing_ids):
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        print("  [google] GOOGLE_API_KEY / GOOGLE_CSE_ID not set, skipping this finder")
        return []

    candidates = []
    seen_urls = set()
    for query in QUERIES:
        params = {"key": api_key, "cx": cse_id, "q": query, "num": 10, "hl": "ko"}
        api_url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        try:
            raw = fetch_text(api_url)
            result = json.loads(raw)
        except Exception as exc:
            print(f"  [google] Custom Search API call failed for {query!r}: {exc}")
            continue
        if "error" in result:
            print(f"  [google] API error for {query!r}: {result['error'].get('message')}")
            continue
        for item in result.get("items", []):
            seen_urls.add(item.get("link"))

    for url in seen_urls:
        if not url:
            continue
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

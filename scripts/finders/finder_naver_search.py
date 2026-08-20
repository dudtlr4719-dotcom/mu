"""Finder: Naver integrated search (search.naver.com).

Casts a much wider net than the two known blogs — catches any blog post
mentioning MUUT, not just the brand's own accounts. But there's no reliable
title pattern to tell a celebrity sighting apart from an ordinary customer's
shopping review or a popup-store visit post, so every candidate here is
handed to the organizer's AI judgment step rather than extracted directly.
"""
import re
import urllib.parse

from common import fetch_text

SOURCE_LABEL = "네이버 통합검색"
KNOWN_BLOG_IDS = {"muut_suwon", "wesee_pr"}  # already covered by dedicated finders
QUERIES = ["MUUT 착용", "뭍 안경 착용"]


def find(existing_ids):
    candidates = []
    seen = set()
    for query in QUERIES:
        url = "https://search.naver.com/search.naver?query=" + urllib.parse.quote(query)
        html = fetch_text(url)
        for m in re.finditer(r'https://blog\.naver\.com/([a-zA-Z0-9_\-]+)/(\d+)', html):
            blog_id, log_no = m.group(1), m.group(2)
            if blog_id in KNOWN_BLOG_IDS:
                continue
            key = (blog_id, log_no)
            if key in seen:
                continue
            seen.add(key)

            eid = f"search-{blog_id}-{log_no}"
            if eid in existing_ids:
                continue

            post_url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
            try:
                post_html = fetch_text(post_url)
            except Exception as exc:
                print(f"  [naver_search] {blog_id}/{log_no}: fetch failed ({exc}), skip")
                continue

            title_m = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
            title = title_m.group(1) if title_m else ""
            if not title or ("muut" not in title.lower() and "뭍" not in title):
                # og:title doesn't even mention the brand — likely a false-positive
                # match on unrelated body text. Not worth an AI call.
                print(f"  [naver_search] {blog_id}/{log_no}: skip (title has no MUUT mention) — {title!r}")
                continue

            candidates.append(
                {
                    "id": eid,
                    "url": post_url,
                    "source_label": SOURCE_LABEL,
                    "note": "네이버 통합검색으로 발견된 게시물",
                    "needs_judgment": True,
                    "title": title,
                    "post_html": post_html,
                }
            )
            print(f"  [naver_search] {blog_id}/{log_no}: candidate for AI judgment — {title!r}")
    return candidates

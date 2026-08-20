"""Finder: muut_suwon — MUUT's own store blog.

Title format is reliable and self-classifying, so this finder does full
extraction itself (no AI judgment needed):
  "[ MUUT ] <celeb> 착용 <product>"  -> a real sighting
  "[ MUUT NEW ARRIVAL ] ..."        -> product announcement, not a sighting
  anything else (store directions etc.) -> not a sighting
"""
import re

from common import fetch_text, parse_naver_date

BLOG_ID = "muut_suwon"
SOURCE_LABEL = "MUUT 수원점 블로그"


def find(existing_ids):
    candidates = []
    list_html = fetch_text(
        f"https://blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0&from=postList"
    )
    log_nos = sorted(set(re.findall(r"logNo=(\d+)", list_html)), key=int, reverse=True)
    for log_no in log_nos:
        eid = f"suwon-{log_no}"
        if eid in existing_ids:
            continue
        url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
        post_html = fetch_text(url)
        title_m = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
        title = title_m.group(1) if title_m else ""
        m = re.match(r"^\[\s*MUUT\s*\]\s*(.+?)\s*착용\s*(.+)$", title)
        if not m:
            print(f"  [suwon] {log_no}: skip (not a sighting-formatted title) — {title!r}")
            continue
        date_iso = parse_naver_date(post_html)
        if not date_iso:
            print(f"  [suwon] {log_no}: skip (no publish date found)")
            continue
        img_m = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)
        candidates.append(
            {
                "id": eid,
                "url": url,
                "date": date_iso,
                "source_label": SOURCE_LABEL,
                "note": "MUUT 수원점 공식 블로그 게시물",
                "needs_judgment": False,
                "name": m.group(1).strip(),
                "product": m.group(2).strip(),
                "image_url": img_m.group(1) if img_m else None,
            }
        )
        print(f"  [suwon] {log_no}: candidate — {m.group(1).strip()} / {m.group(2).strip()}")
    return candidates

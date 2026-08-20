"""Finder: wesee_pr — multi-brand PR blog.

og:title format is reliable and self-classifying, so this finder does full
extraction itself (no AI judgment needed):
  "MUUT 뭍 <celeb + context> 착용 <generic desc> 정보 ... 브랜드 추천"

The real product/model name lives in an embedded Naver oglink card pointing
at muut.co.kr or misekiseoul.kr (their own instagram self-promo oglink is a
separate card further down the post — skip it).
"""
import re

from common import fetch_text, parse_naver_date

BLOG_ID = "wesee_pr"
SOURCE_LABEL = "WESEE.PR 블로그"


def _extract_product(post_html):
    for m in re.finditer(r'<strong class="se-oglink-title">([^<]*)', post_html):
        title = m.group(1).strip()
        if "WESEE" in title.upper() or "INSTAGRAM" in title.upper():
            continue
        return title
    return None


def _pick_image_url(post_html):
    # 1) best: a file literally named 1.png (WESEE.PR's own person+product composite)
    one_png = re.search(r'(https://postfiles\.pstatic\.net/[^"]+/1\.png)', post_html)
    if one_png:
        return one_png.group(1) + "?type=w966"
    # 2) good: candid photo (any postfiles jpg that isn't the fixed watermark logo)
    for m in re.finditer(r'(https://postfiles\.pstatic\.net/[^"]+\.(?:jpg|jpeg))', post_html, re.I):
        url = m.group(1)
        if "MjAyMzA0MjVfOTUg" in url:
            continue
        return url
    # 3) last resort: og:image
    img_m = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)
    return img_m.group(1) if img_m else None


def find(existing_ids):
    candidates = []
    seen_lognos = set()
    for page in range(1, 6):  # ~50 most recent muut-tagged posts is plenty
        search_html = fetch_text(
            f"https://blog.naver.com/PostSearchList.naver?blogId={BLOG_ID}&categoryNo=0"
            f"&SearchText=muut&orderBy=date&range=all&cpage={page}"
        )
        page_lognos = re.findall(r"logNo=(\d+)", search_html)
        if not page_lognos:
            break
        seen_lognos.update(page_lognos)

    for log_no in sorted(seen_lognos, key=int, reverse=True):
        eid = f"wesee-{log_no}"
        if eid in existing_ids:
            continue
        url = f"https://blog.naver.com/PostView.naver?blogId={BLOG_ID}&logNo={log_no}"
        post_html = fetch_text(url)
        title_m = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
        title = title_m.group(1) if title_m else ""
        m = re.match(r"^MUUT\s*뭍?\s*(.+?)\s*착용", title)
        if not m:
            print(f"  [wesee] {log_no}: skip (title doesn't match sighting pattern) — {title!r}")
            continue
        date_iso = parse_naver_date(post_html)
        if not date_iso:
            print(f"  [wesee] {log_no}: skip (no publish date found)")
            continue
        name = m.group(1).strip()
        product = _extract_product(post_html) or "MUUT 아이웨어 (모델명 미상)"
        candidates.append(
            {
                "id": eid,
                "url": url,
                "date": date_iso,
                "source_label": SOURCE_LABEL,
                "note": "WESEE.PR 블로그 게시물",
                "needs_judgment": False,
                "name": name,
                "product": product,
                "image_url": _pick_image_url(post_html),
            }
        )
        print(f"  [wesee] {log_no}: candidate — {name} / {product}")
    return candidates

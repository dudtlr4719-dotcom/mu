#!/usr/bin/env python3
"""
MUUT SPOTTED monitor — scrapes muut_suwon and wesee_pr Naver blogs for new
MUUT eyewear celebrity sightings, updates index.html's embedded JSON, and
downloads sighting images into images/. Runs entirely inside GitHub Actions
(github.com's own infra), so no cross-service credential handoff is needed.
"""
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
INDEX_PATH = "index.html"
IMAGES_DIR = "images"
MIN_ENTRIES = 90  # safety check: repo should already have at least this many


def fetch(url, referer=None, timeout=20):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_text(url, referer=None):
    return fetch(url, referer=referer).decode("utf-8", errors="replace")


def load_data():
    html = open(INDEX_PATH, encoding="utf-8").read()
    m = re.search(r'(<script[^>]*id="sightings-data"[^>]*>)(.*?)(</script>)', html, re.S)
    if not m:
        raise SystemExit("sightings-data script tag not found in index.html")
    data = json.loads(m.group(2))
    return html, data, m


def save_data(html, data, m):
    new_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_html = html[: m.start(2)] + new_json + html[m.end(2):]
    open(INDEX_PATH, "w", encoding="utf-8").write(new_html)


def toks(s):
    return set(re.findall(r"[가-힣A-Za-z0-9]+", s))


def is_dupe(new_name, new_date_iso, entries, window_days=10):
    try:
        nd = datetime.fromisoformat(new_date_iso[:19])
    except ValueError:
        return False
    new_toks = toks(new_name)
    for e in entries:
        try:
            ed = datetime.fromisoformat(e["date"][:19])
        except (KeyError, ValueError):
            continue
        if abs((nd - ed).days) <= window_days and (toks(e["name"]) & new_toks):
            return True
    return False


def parse_naver_date(post_html):
    m = re.search(r'se_publishDate pcol2">\s*(\d+)\.\s*(\d+)\.\s*(\d+)\.\s*(\d+):(\d+)', post_html)
    if not m:
        return None
    y, mo, d, hh, mm = (int(x) for x in m.groups())
    return datetime(y, mo, d, hh, mm).strftime("%Y-%m-%dT%H:%M:00+09:00")


def download_image(url, dest_path, referer="https://blog.naver.com/"):
    try:
        raw = fetch(url, referer=referer)
    except Exception as exc:
        print(f"  image download failed ({url}): {exc}")
        return False
    if len(raw) < 2000:  # placeholder/blocked-hotlink images are tiny
        return False
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.save(dest_path, "JPEG", quality=90)
    except Exception:
        # Pillow unavailable or decode failed — save raw bytes as-is
        open(dest_path, "wb").write(raw)
    return True


# ---------------------------------------------------------------------------
# Source A: muut_suwon — MUUT's own store blog. Authoritative for celeb name
# + exact model code. Post titles are one of:
#   "[ MUUT ] <celeb> 착용 <product>"       -> a real sighting
#   "[ MUUT NEW ARRIVAL ] ..."              -> product announcement, skip
#   anything else (e.g. store directions)   -> skip
# ---------------------------------------------------------------------------
def check_suwon(existing_ids):
    new_entries = []
    list_html = fetch_text(
        "https://blog.naver.com/PostList.naver?blogId=muut_suwon&categoryNo=0&from=postList"
    )
    log_nos = sorted(set(re.findall(r"logNo=(\d+)", list_html)), key=int, reverse=True)
    for log_no in log_nos:
        eid = f"suwon-{log_no}"
        if eid in existing_ids:
            continue
        url = f"https://blog.naver.com/PostView.naver?blogId=muut_suwon&logNo={log_no}"
        post_html = fetch_text(url)
        title_m = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
        title = title_m.group(1) if title_m else ""
        m = re.match(r"^\[\s*MUUT\s*\]\s*(.+?)\s*착용\s*(.+)$", title)
        if not m:
            print(f"  suwon {log_no}: skip (not a sighting post) — {title!r}")
            continue
        name, product = m.group(1).strip(), m.group(2).strip()
        date_iso = parse_naver_date(post_html)
        if not date_iso:
            print(f"  suwon {log_no}: skip (no publish date found)")
            continue
        img_m = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)
        photo_uri = None
        if img_m:
            dest = os.path.join(IMAGES_DIR, f"{eid}.jpg")
            if download_image(img_m.group(1), dest):
                photo_uri = f"{IMAGES_DIR}/{eid}.jpg"
        new_entries.append(
            {
                "id": eid,
                "date": date_iso,
                "name": name,
                "product": product,
                "note": "MUUT 수원점 공식 블로그 게시물",
                "source": "MUUT 수원점 블로그",
                "url": url,
                **({"photoDataUri": photo_uri} if photo_uri else {}),
            }
        )
        print(f"  suwon {log_no}: NEW sighting — {name} / {product}")
    return new_entries


# ---------------------------------------------------------------------------
# Source B: wesee_pr — multi-brand PR blog. og:title format is always:
#   "MUUT 뭍 <celeb + context> 착용 <generic description> 정보 ... 브랜드 추천"
# The real product name/code lives in an embedded Naver oglink card pointing
# at muut.co.kr or misekiseoul.kr (their own instagram self-promo oglink is
# always a second, separate card — skip it).
# ---------------------------------------------------------------------------
def extract_product(post_html):
    for m in re.finditer(r'<strong class="se-oglink-title">([^<]*)', post_html):
        title = m.group(1).strip()
        if "WESEE" in title.upper() or "INSTAGRAM" in title.upper():
            continue
        return title
    return None


def pick_wesee_image(post_html, eid):
    dest = os.path.join(IMAGES_DIR, f"{eid}.jpg")
    # 1) best: a file literally named 1.png (WESEE.PR's own person+product composite)
    one_png = re.search(r'(https://postfiles\.pstatic\.net/[^"]+/1\.png)', post_html)
    if one_png:
        url = one_png.group(1) + "?type=w966"
        if download_image(url, dest):
            return f"{IMAGES_DIR}/{eid}.jpg"
    # 2) good: candid photo named <celeb>_(N).jpg
    for m in re.finditer(r'(https://postfiles\.pstatic\.net/[^"]+\.(?:jpg|jpeg))', post_html, re.I):
        url = m.group(1)
        if "MjAyMzA0MjVfOTUg" in url:  # fixed wesee_pr watermark logo, always skip
            continue
        if download_image(url, dest):
            return f"{IMAGES_DIR}/{eid}.jpg"
    # 3) last resort: og:image
    img_m = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)
    if img_m and download_image(img_m.group(1), dest):
        return f"{IMAGES_DIR}/{eid}.jpg"
    return None


def check_wesee(existing_ids, existing_entries):
    new_entries = []
    seen_lognos = set()
    for page in range(1, 6):  # 5 pages / ~50 most recent muut-tagged posts is plenty
        search_html = fetch_text(
            "https://blog.naver.com/PostSearchList.naver?blogId=wesee_pr&categoryNo=0"
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
        url = f"https://blog.naver.com/PostView.naver?blogId=wesee_pr&logNo={log_no}"
        post_html = fetch_text(url)
        title_m = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
        title = title_m.group(1) if title_m else ""
        m = re.match(r"^MUUT\s*뭍?\s*(.+?)\s*착용", title)
        if not m:
            print(f"  wesee {log_no}: skip (title doesn't match sighting pattern) — {title!r}")
            continue
        name = m.group(1).strip()
        date_iso = parse_naver_date(post_html)
        if not date_iso:
            print(f"  wesee {log_no}: skip (no publish date found)")
            continue
        if is_dupe(name, date_iso, existing_entries) or is_dupe(name, date_iso, new_entries):
            print(f"  wesee {log_no}: skip (dedup match, likely already on site) — {name}")
            continue
        product = extract_product(post_html) or "MUUT 아이웨어 (모델명 미상)"
        photo_uri = pick_wesee_image(post_html, eid)
        entry = {
            "id": eid,
            "date": date_iso,
            "name": name,
            "product": product,
            "note": "WESEE.PR 블로그 게시물",
            "source": "WESEE.PR 블로그",
            "url": url,
            **({"photoDataUri": photo_uri} if photo_uri else {}),
        }
        new_entries.append(entry)
        print(f"  wesee {log_no}: NEW sighting — {name} / {product}")
    return new_entries


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)
    html, data, m = load_data()
    entries = data["entries"]
    if len(entries) < MIN_ENTRIES:
        print(f"SAFETY ABORT — only {len(entries)} entries parsed, expected >= {MIN_ENTRIES}. No changes made.")
        sys.exit(1)

    existing_ids = {e["id"] for e in entries}
    print(f"Loaded {len(entries)} existing entries. Checking sources...")

    print("Checking muut_suwon...")
    suwon_new = check_suwon(existing_ids)

    print("Checking wesee_pr...")
    wesee_new = check_wesee(existing_ids, entries)

    all_new = suwon_new + wesee_new
    data["lastChecked"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if all_new:
        data["entries"].extend(all_new)

    save_data(html, data, m)

    print(f"\n=== Summary: {len(all_new)} new mention(s) added ===")
    for e in all_new:
        print(f"  + {e['name']} — {e['product']} ({e['url']})")

    # Signal to the workflow whether there's anything worth notifying about.
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as f:
            f.write(f"new_count={len(all_new)}\n")
            summary = "; ".join(f"{e['name']} ({e['product']})" for e in all_new)
            f.write(f"new_summary={summary}\n")


if __name__ == "__main__":
    main()

"""Shared utilities for the MUUT SPOTTED monitor.

Two kinds of "agents" live in this package:
- finders/*.py  — each scans one source and returns raw Candidate dicts.
                   A finder never decides relevance; it just surfaces posts
                   that mention MUUT. Cheap, deterministic, no AI calls.
- organizer.py  — takes all candidates from all finders, judges each one
                   (is this really a celebrity/influencer sighting?), extracts
                   the celebrity name + product, dedups, picks an image, and
                   writes the result into index.html.
"""
import io
import json
import re
import urllib.request
from datetime import datetime

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
INDEX_PATH = "index.html"
IMAGES_DIR = "images"


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


def parse_naver_date(post_html):
    """'se_publishDate pcol2">2026. 8. 14. 11:48' -> '2026-08-14T11:48:00+09:00'"""
    m = re.search(r'se_publishDate pcol2">\s*(\d+)\.\s*(\d+)\.\s*(\d+)\.\s*(\d+):(\d+)', post_html)
    if not m:
        return None
    y, mo, d, hh, mm = (int(x) for x in m.groups())
    return datetime(y, mo, d, hh, mm).strftime("%Y-%m-%dT%H:%M:00+09:00")


def parse_generic_date(html):
    """Best-effort date extraction for non-Naver pages (news sites, blogs, etc.)."""
    for pattern in (
        r'<meta property="article:published_time" content="([^"]+)"',
        r'<meta property="og:updated_time" content="([^"]+)"',
        r'<meta itemprop="datePublished" content="([^"]+)"',
        r'<time[^>]+datetime="([^"]+)"',
    ):
        m = re.search(pattern, html)
        if m:
            raw = m.group(1)
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                return dt.strftime("%Y-%m-%dT%H:%M:00+09:00")
            offset = dt.utcoffset()
            total_min = int(offset.total_seconds() // 60)
            sign = "+" if total_min >= 0 else "-"
            hh, mm = divmod(abs(total_min), 60)
            return dt.strftime("%Y-%m-%dT%H:%M:00") + f"{sign}{hh:02d}:{mm:02d}"
    return None


def generic_image_url(html):
    m = re.search(r'<meta property="og:image" content="([^"]*)"', html)
    return m.group(1) if m else None


def toks(s):
    return set(re.findall(r"[가-힣A-Za-z0-9]+", s))


def is_dupe(new_name, new_date_iso, entries, window_days=10):
    """Fuzzy dedup: same name tokens overlap within +/-window_days."""
    try:
        nd = datetime.fromisoformat(new_date_iso[:19])
    except ValueError:
        return False
    new_toks = toks(new_name)
    if not new_toks:
        return False
    for e in entries:
        try:
            ed = datetime.fromisoformat(e["date"][:19])
        except (KeyError, ValueError):
            continue
        if abs((nd - ed).days) <= window_days and (toks(e["name"]) & new_toks):
            return True
    return False


def download_image(url, dest_path, referer="https://blog.naver.com/"):
    try:
        raw = fetch(url, referer=referer)
    except Exception as exc:
        print(f"    image download failed ({url}): {exc}")
        return False
    if len(raw) < 2000:  # placeholder/blocked-hotlink images are tiny
        return False
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.save(dest_path, "JPEG", quality=90)
    except Exception:
        open(dest_path, "wb").write(raw)
    return True

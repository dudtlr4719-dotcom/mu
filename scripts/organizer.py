"""Organizer: takes candidates from all finders and turns them into site entries.

Trusted-source candidates (needs_judgment=False, from finder_suwon/finder_wesee)
already have name/product/image resolved — the organizer just dedups, downloads
the image, and appends them.

Broad-source candidates (needs_judgment=True, e.g. from finder_naver_search)
get judged by Claude first: is this actually a celebrity/influencer wearing
MUUT, or an ordinary customer's shopping review / popup-store visit post?
Only ones the model confirms as real sightings get added.
"""
import os
import re
import sys

from common import IMAGES_DIR, download_image, is_dupe

MODEL = "claude-haiku-4-5-20251001"


def _strip_tags(html, limit=3000):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _pick_image_url(post_html):
    one_png = re.search(r'(https://postfiles\.pstatic\.net/[^"]+/1\.png)', post_html)
    if one_png:
        return one_png.group(1) + "?type=w966"
    for m in re.finditer(r'(https://postfiles\.pstatic\.net/[^"]+\.(?:jpg|jpeg))', post_html, re.I):
        url = m.group(1)
        if "MjAyMzA0MjVfOTUg" in url:
            continue
        return url
    img_m = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)
    return img_m.group(1) if img_m else None


def _judge_with_claude(client, candidate, known_names):
    from common import parse_naver_date

    body_text = _strip_tags(candidate["post_html"])
    prompt = (
        "You're screening a Naver blog post for a fashion brand's celebrity-sighting "
        "tracker. The brand is MUUT (Korean: 뭍), a Korean eyewear brand.\n\n"
        f"Post title: {candidate['title']}\n"
        f"Post body (truncated, tags stripped): {body_text}\n\n"
        "Decide: is this post itself a PRIMARY report/sighting of a named celebrity, "
        "idol, or influencer wearing/using a MUUT product — e.g. the poster is the "
        "brand/PR account, or is directly describing/showing an event, appearance, "
        "photo, or broadcast where that person was seen wearing it?\n\n"
        "Say NO (is_celebrity_sighting=false) if the post is really about the "
        "AUTHOR'S OWN purchase/review and merely REFERENCES a celebrity's "
        "already-known or already-famous association with the product as a selling "
        "point — phrases like '~가 착용한 것으로 유명한', '~가 착용해서 화제가 된', "
        "'~가 착용한 걸로 잘 알려진', '~착용템으로 유명한' are exactly this pattern "
        "and must be rejected, even though a celebrity name appears. Ordinary "
        "customer shopping reviews, popup-store visit posts, and general brand "
        "coverage with no named individual also do NOT count.\n\n"
        "If yes (a genuine primary sighting), extract the celebrity's name (Korean, "
        "as commonly written) and the product name/model if mentioned (otherwise null)."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        tools=[
            {
                "name": "classify_sighting",
                "description": "Report whether this post is a genuine celebrity MUUT sighting.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "is_celebrity_sighting": {"type": "boolean"},
                        "celebrity_name": {"type": ["string", "null"]},
                        "product": {"type": ["string", "null"]},
                    },
                    "required": ["is_celebrity_sighting", "celebrity_name", "product"],
                },
            }
        ],
        tool_choice={"type": "tool", "name": "classify_sighting"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            result = block.input
            result["date"] = parse_naver_date(candidate["post_html"])
            return result
    return None


def organize(candidates, existing_entries):
    new_entries = []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = None

    to_judge = [c for c in candidates if c.get("needs_judgment")]
    if to_judge and not api_key:
        print(f"  WARNING: {len(to_judge)} candidate(s) need AI judgment but "
              f"ANTHROPIC_API_KEY is not set — skipping them.")
        to_judge = []
    elif to_judge:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

    known_names = [e["name"] for e in existing_entries]

    for c in candidates:
        if c.get("needs_judgment"):
            try:
                verdict = _judge_with_claude(client, c, known_names)
            except Exception as exc:
                print(f"  [organizer] judgment call failed for {c['id']}: {exc}")
                continue
            if not verdict or not verdict.get("is_celebrity_sighting"):
                print(f"  [organizer] {c['id']}: AI judged NOT a celebrity sighting, skip")
                continue
            name = (verdict.get("celebrity_name") or "").strip()
            if not name:
                print(f"  [organizer] {c['id']}: AI confirmed sighting but no name extracted, skip")
                continue
            product = (verdict.get("product") or "MUUT 아이웨어 (모델명 미상)").strip()
            date_iso = verdict.get("date")
            if not date_iso:
                print(f"  [organizer] {c['id']}: no publish date found, skip")
                continue
            image_url = _pick_image_url(c["post_html"])
        else:
            name, product, date_iso = c["name"], c["product"], c["date"]
            image_url = c.get("image_url")

        if is_dupe(name, date_iso, existing_entries) or is_dupe(name, date_iso, new_entries):
            print(f"  [organizer] {c['id']}: skip (dedup match) — {name}")
            continue

        photo_uri = None
        if image_url:
            dest = os.path.join(IMAGES_DIR, f"{c['id']}.jpg")
            if download_image(image_url, dest):
                photo_uri = f"{IMAGES_DIR}/{c['id']}.jpg"

        entry = {
            "id": c["id"],
            "date": date_iso,
            "name": name,
            "product": product,
            "note": c["note"],
            "source": c["source_label"],
            "url": c["url"],
            **({"photoDataUri": photo_uri} if photo_uri else {}),
        }
        new_entries.append(entry)
        print(f"  [organizer] {c['id']}: ADDED — {name} / {product}")

    return new_entries

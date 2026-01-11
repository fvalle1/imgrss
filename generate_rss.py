import os
from datetime import datetime, timezone
from instagrapi import Client
from instagrapi.exceptions import TwoFactorRequired, ChallengeRequired
from feedgen.feed import FeedGenerator
from pathlib import Path
import pyotp
import random
import unicodedata

FEEDS_DIR = "feeds"
MAX_POSTS = 20
BASE_URL = "https://raw.githubusercontent.com/fvalle1/imgrss/refs/heads/main/feeds"
SESSION_FILE = "ig_session.json"

def ig_login():
    cl = Client()
    
    cl.set_device({
        "app_version": "302.0.0.23.109",
        "android_version": 0,  # not used for iOS
        "android_release": "",
        "dpi": "326dpi",
        "resolution": "1170x2532",
        "manufacturer": "Apple",
        "device": "iPhone13,4",
        "model": "iPhone",
        "cpu": "arm64-v8a",
        "version_code": "302001109",
        "platform": "iOS",
        "os_version": "17.1"
    })
    
    session_json = os.getenv("IG_SESSION_JSON")
    if session_json:
        with open(SESSION_FILE, "w") as f:
            f.write(session_json)

    if os.path.exists(SESSION_FILE):
        cl.load_settings(SESSION_FILE)

    username = os.environ["IG_USERNAME"]
    password = os.environ["IG_PASSWORD"]

    try:
        cl.login(username, password)
        return cl

    except TwoFactorRequired:
        secret = os.environ.get("IG_TOTP_SECRET")
        if not secret:
            raise RuntimeError("2FA required but IG_TOTP_SECRET not set")

        code = pyotp.TOTP(secret).now()
        cl.login(username, password, verification_code=code)

    except ChallengeRequired:
        raise RuntimeError(
            "Instagram checkpoint/challenge required. "
            "Approve it in the app/browser, then rerun."
        )

    cl.dump_settings(SESSION_FILE)
    return cl

def clean_text(text):
    """
    Rimuove i font speciali di Instagram (grassetti matematici, ecc.) 
    e li converte in testo standard leggibile dai feed reader.
    """
    if not text:
        return ""
    # Normalizzazione NFKC: trasforma i caratteri speciali "estetici" in caratteri normali
    return unicodedata.normalize('NFKC', text)

def create_feed_dir():
    Path(FEEDS_DIR).mkdir(exist_ok=True)

def ts_to_dt_utc(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)

def pick_image_url(item: dict) -> str | None:
    # For photos + albums, Instagram returns candidates
    # Try common locations
    if "image_versions2" in item:
        candidates = item["image_versions2"].get("candidates") or []
        if candidates:
            return candidates[0].get("url")

    # Carousels store images in carousel_media
    carousel = item.get("carousel_media") or []
    for m in carousel:
        if "image_versions2" in m:
            candidates = m["image_versions2"].get("candidates") or []
            if candidates:
                return candidates[0].get("url")

    # Reels/videos may have thumbnail_url-ish fields
    return None

def caption_text(item: dict) -> str:
    cap = item.get("caption")
    if isinstance(cap, dict):
        return clean_text((cap.get("text") or "").strip())
    return ""

def permalink_from_code(code: str) -> str:
    return f"https://www.instagram.com/p/{code}/" if code else ""

def fetch_user_items_raw(cl: Client, username: str, amount: int):
    user_id = cl.user_id_from_username(username)

    data = cl.private_request(
        f"feed/user/{user_id}/",
        params={"count": amount}
    )
    return data.get("items", [])

def generate_rss_for_account(cl: Client, account_name: str):
    items = fetch_user_items_raw(cl, account_name, MAX_POSTS)
    if not items:
        print(f"✗ No items for @{account_name}")
        return

    fg = FeedGenerator()
    fg.title(f"@{account_name} - Instagram")
    fg.link(href=f"https://www.instagram.com/{account_name}/", rel="alternate")
    fg.link(href=f"{BASE_URL}/{account_name}.xml", rel="self")
    fg.description(f"Instagram posts from @{account_name}")
    fg.language("en")

    for it in items:
        code = it.get("code")  # shortcode
        url = permalink_from_code(code)

        img = pick_image_url(it)
        cap = caption_text(it)
        taken_at = it.get("taken_at") or it.get("device_timestamp")

        fe = fg.add_entry()
        fe.id(url or str(it.get("pk") or code))
        fe.link(href=url or f"https://www.instagram.com/{account_name}/")
        fe.title(cap[:100].replace("\n", " ") if cap else f"Post by @{account_name}")

        desc = ""
        if img:
            desc += f'<img src="{img}" alt="Instagram post"/><br/><br/>'
        if cap:
            desc += cap.replace("\n", "<br/>")
        fe.description(desc)

        if taken_at:
            fe.pubDate(ts_to_dt_utc(taken_at))

    feed_path = os.path.join(FEEDS_DIR, f"{account_name}.xml")
    fg.rss_file(feed_path, pretty=True)
    print(f"✓ Generated feed for @{account_name} ({len(items)} items)")

def main():
    create_feed_dir()
    cl = ig_login()

    accounts = os.getenv("ACCOUNTS", "")
    accounts = [a.strip() for a in accounts.split(",") if a.strip()]

    random.shuffle(accounts)

    for a in accounts[:5]:
        generate_rss_for_account(cl, a)

if __name__ == "__main__":
    main()

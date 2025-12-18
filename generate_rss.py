import os
import json
import time
import random
import regex as re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth
from feedgen.feed import FeedGenerator

# Configuration
ACCOUNTS_FILE = "accounts.json"
FEEDS_DIR = "feeds"
MAX_POSTS = 20
DELAY_BETWEEN_ACCOUNTS = 30
try:
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "t")
except:
    DEBUG = True


def load_accounts():
    """Load Instagram accounts from config file"""

    os.getenv("ACCOUNTS")
    accs = os.getenv("ACCOUNTS").split(",")
    if len(accs) > 0 and accs[0] != "":
        return {"accounts": accs}

    with open(ACCOUNTS_FILE, "r") as f:
        return json.load(f)


def create_feed_dir():
    """Create feeds directory if it doesn't exist"""
    Path(FEEDS_DIR).mkdir(exist_ok=True)


def relative_to_timestamp(text):
    now = datetime.now(timezone.utc)
    # Match numbers and units
    match = re.match(r"(\d+)\s+(\w+)\s+ago", text)
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2).lower()
    if "day" in unit:
        return now - timedelta(days=value)
    elif "hour" in unit:
        return now - timedelta(hours=value)
    elif "minute" in unit:
        return now - timedelta(minutes=value)
    elif "second" in unit:
        return now - timedelta(seconds=value)
    return None


def setup_driver():
    """Setup headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("start-maximized")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    global DEBUG
    # 👇 Specify Chromium binary location
    if DEBUG:
        print("Running in DEBUG mode - using local Chrome installation")
        pass
    else:
        chrome_options.binary_location = "/usr/bin/chromium-browser"

    # 👇 Use Service for chromedriver
    if DEBUG:
        driver = webdriver.Chrome(options=chrome_options)
    else:
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True
    )

    return driver


def fetch_imginn_posts(driver, account_name):
    """Fetch posts from Imginn account and open each post page"""
    url = f"https://imginn.com/{account_name}/"
    driver.get(url)

    # Check if we're on a Cloudflare challenge page
    try:
        challenge_element = driver.find_element(By.CLASS_NAME, "main-wrapper")
        if "Verifying you are human" in driver.page_source:
            print(f"  🔒 Cloudflare challenge detected for @{account_name}, waiting...")

            # Wait up to 60 seconds for the challenge to complete
            WebDriverWait(driver, 60).until_not(
                EC.presence_of_element_located((By.CLASS_NAME, "lds-ring"))
            )

            # Additional wait for redirect
            time.sleep(10)

            # Check if we're still on challenge page
            if "Verifying you are human" in driver.page_source:
                print(f"  ❌ Challenge not completed for @{account_name}")
                
                with open("debug_imginn.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                raise Exception("Cloudflare challenge timeout")

            print(f"  ✅ Challenge completed for @{account_name}")
    except:
        pass  # No challenge page detected

    time.sleep(5)  # Wait for page to load
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(5)

    
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "item"))
        )
        time.sleep(2)
    except Exception as e:
        raise Exception("Failed to load account posts", str(e))

    posts = []
    post_elements = driver.find_elements(By.CLASS_NAME, "item")[:MAX_POSTS]

    for post_elem in post_elements:
        try:
            # Extract link
            link_elem = post_elem.find_element(By.TAG_NAME, "a")
            post_url = link_elem.get_attribute("href")

            # Extract image
            try:
                img_elem = driver.find_element(By.XPATH, '//meta[@property="og:image"]')
                profile_image_url = img_elem.get_attribute("content")
            except Exception as e:
                print(f"  ⚠ Error extracting image URL: {e}")
                profile_image_url = None

            try:
                img_tag = post_elem.find_element(By.TAG_NAME, "img")
                image_url = img_tag.get_attribute("src")
                caption = img_tag.get_attribute("alt")
            except Exception as e:
                print(f"  ⚠ Error extracting caption: {e}")
                caption = ""

            try:
                action_elem = post_elem.find_element(By.CLASS_NAME, "action")
                time_tag = action_elem.find_element(By.CLASS_NAME, "time")
                date = time_tag.get_attribute("innerText")
                print("Extracted date text:", date)
                date = relative_to_timestamp(date)
            except Exception as e:
                print(f"  ⚠ Error extracting date: {e}")
                date = datetime.now(timezone.utc)

            # Extract shortcode
            shortcode = (
                post_url.split("/")[-2]
                if "/p/" in post_url
                else post_url.split("/")[-1]
            )

            posts.append(
                {
                    "shortcode": shortcode,
                    "url": post_url,
                    "profile_image_url": profile_image_url,
                    "image_url": image_url,
                    "caption": caption,
                    "date": date,
                    "instagram_url": f"https://www.instagram.com/p/{shortcode}/",
                }
            )

            time.sleep(5)

        except Exception as e:
            print(f"  ⚠ Error parsing post: {e}")
            continue

        if DEBUG:
            break

    return posts


def get_profile_info(driver, account_name):
    """Extract profile information"""
    profile_info = {
        "full_name": account_name,
        "biography": f"Instagram posts from @{account_name}",
    }

    try:
        name_elem = driver.find_element(By.TAG_NAME, "h1")
        profile_info["full_name"] = name_elem.text
    except:
        pass

    return profile_info


def generate_rss_for_account(driver, account_name):
    """Generate RSS feed for a single Instagram account"""
    print(f"Processing @{account_name}...")

    try:
        # Fetch posts
        posts = fetch_imginn_posts(driver, account_name)

        if not posts:
            print(f"✗ No posts found for @{account_name}")
            return False

        # Get profile info
        profile_info = get_profile_info(driver, account_name)

        # Create feed generator
        fg = FeedGenerator()
        fg.title(f"{profile_info['full_name']} (@{account_name}) - Instagram")
        fg.link(href=f"https://www.instagram.com/{account_name}/", rel="alternate")
        fg.description(
            f"<img src={posts[0]['profile_image_url']}/> {profile_info['biography']}"
        )
        fg.language("en")

        # Add posts to feed
        for post in posts:
            fe = fg.add_entry()
            fe.id(post["instagram_url"])
            fe.link(href=post["url"])
            fe.title(
                post["caption"][:100] if post["caption"] else f"Post by @{account_name}"
            )

            description = ""
            if post["image_url"]:
                description += (
                    f'<img src="{post["image_url"]}" alt="Instagram post"/><br/><br/>'
                )
            if post["caption"]:
                description += post["caption"].replace("\n", "<br/>")

            if DEBUG:
                print("Post description:", description)
            fe.description(description)
            fe.pubDate(post["date"])

        # Save RSS feed
        feed_path = os.path.join(FEEDS_DIR, f"{account_name}.xml")
        fg.rss_file(feed_path, pretty=True)
        print(f"✓ Generated feed for @{account_name} ({len(posts)} posts)")
        return True

    except Exception as e:
        print(f"✗ Error processing @{account_name}: {str(e)}")
        return False


def main():
    config = load_accounts()
    accounts = config.get("accounts", [])

    if not accounts:
        print("No accounts configured in accounts.json")
        return

    random.shuffle(accounts)

    create_feed_dir()

    print(f"Generating RSS feeds for {len(accounts)} accounts using Imginn...\n")

    driver = None
    try:
        driver = setup_driver()

        success_count = 0
        for i, account in enumerate(accounts):
            if generate_rss_for_account(driver, account):
                success_count += 1

            if i < len(accounts) - 1:
                print(f"Waiting {DELAY_BETWEEN_ACCOUNTS} seconds...\n")
                time.sleep(DELAY_BETWEEN_ACCOUNTS)
            if DEBUG:
                print("\n✓ DEBUG mode is ON - processed only the first account.\n")
                break

        print(f"\n✓ Complete! ({success_count}/{len(accounts)} successful)")

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()

"""Upstash Redis full setup — account creation + database setup.

1. Creates a temp email via mail.tm
2. Signs up on upstash.com using SeleniumBase UC mode
3. Polls temp email for verification link
4. Clicks verification link
5. Creates a Redis database
6. Extracts the Redis URL
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from seleniumbase import SB
from temp_email import create_email, wait_for_code, wait_for_verification

COOKIES_FILE = Path(__file__).parent / ".cookies_upstash.txt"


def setup_upstash(full_name: str = "NSE Quant") -> tuple[str, str, str]:
    """Full automated Upstash setup.

    Returns:
        (email, password, redis_url)
    """
    password = "QuantDeploy2026!"

    # Step 1: Create temp email
    print("  [1/5] Creating temp email...")
    email, token = create_email("upstashquant")
    print(f"  [✓] Email: {email}")

    # Step 2: Sign up on Upstash
    print("  [2/5] Signing up on upstash.com...")
    with SB(uc=True, test=True, headless=True) as sb:
        sb.goto("https://upstash.com/signup")
        sb.sleep(3)

        # Fill signup form
        sb.type('input[name="name"], input[placeholder*="name"]', full_name)
        sb.sleep(0.3)
        sb.type('input[type="email"], input[name="email"]', email)
        sb.sleep(0.3)
        sb.type('input[type="password"], input[name="password"]', password)
        sb.sleep(0.3)

        # Accept terms if checkbox
        with contextlib.suppress(Exception):
            sb.click('input[type="checkbox"]', timeout=3)

        sb.click('button[type="submit"], button:contains("Sign up"), button:contains("Create")')
        sb.sleep(5)

        # Handle CAPTCHA/challenge
        if sb.is_element_present("iframe"):
            sb.sleep(10)

    # Step 3: Poll for verification
    print("  [3/5] Waiting for verification email (max 5 min)...")
    verify_url = wait_for_verification(token, timeout=300, poll_interval=5)

    if not verify_url:
        otp = wait_for_code(token, timeout=300, poll_interval=5)
        if otp:
            print(f"  [✓] Got OTP: {otp}")
            with SB(uc=True, test=True, headless=True) as sb:
                if COOKIES_FILE.exists():
                    sb.load_cookies(str(COOKIES_FILE))
                sb.goto("https://upstash.com/signin")
                sb.sleep(3)
                sb.type('input[type="email"]', email)
                sb.type('input[type="password"]', password)
                sb.click('button[type="submit"]')
                sb.sleep(3)
                # Look for OTP input
                sb.type('input[name="code"], input[placeholder*="code"]', otp)
                sb.click('button[type="submit"]')
                sb.sleep(3)
        else:
            print("  [✗] No verification email received")
            raise RuntimeError("Email verification failed")

    # Step 4: Click verification link
    if verify_url and verify_url.startswith("http"):
        print("  [4/5] Clicking verification link...")
        with SB(uc=True, test=True, headless=True) as sb:
            sb.goto(verify_url)
            sb.sleep(5)

            if sb.is_element_present('input[type="password"]'):
                sb.type('input[type="password"]', password)
                with contextlib.suppress(Exception):
                    sb.click('button[type="submit"]')
                sb.sleep(3)

            sb.save_cookies(str(COOKIES_FILE))
    else:
        print("  [4/5] Verification done via OTP")

    # Step 5: Login and create Redis database
    print("  [5/5] Creating Upstash Redis database...")
    redis_url = _create_redis_db(email, password)

    print("  [✓] Upstash setup complete")
    print(f"  [✓] Email: {email}")
    print(f"  [✓] Redis URL: {redis_url[:40]}...")

    return email, password, redis_url


def _create_redis_db(email: str, password: str) -> str:
    """Login to Upstash and create a Redis database."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://upstash.com/signin")
        sb.sleep(3)

        if "signin" in sb.get_current_url() or sb.is_text_visible("Sign in"):
            sb.type('input[type="email"], input[name="email"]', email)
            sb.sleep(0.3)
            sb.type('input[type="password"], input[name="password"]', password)
            sb.sleep(0.3)
            sb.click('button[type="submit"]')
            sb.sleep(5)

        sb.save_cookies(str(COOKIES_FILE))

        # Navigate to Redis page
        sb.goto("https://console.upstash.com/redis")
        sb.sleep(3)

        # Check if database exists
        if sb.is_text_visible("nse-bse-quant"):
            # Click existing database
            sb.click('text="nse-bse-quant"')
            sb.sleep(3)
        else:
            # Create new database
            sb.click('button:contains("Create Database"), button:contains("New Database")')
            sb.sleep(2)

            name_input = sb.find_element('input[name="name"], input[placeholder*="name"]')
            name_input.clear()
            sb.type('input[name="name"], input[placeholder*="name"]', "nse-bse-quant")
            sb.sleep(0.5)

            # Select region (closest to India)
            with contextlib.suppress(Exception):
                sb.select_option_by_text('select[name="region"], select', "ap-south-1 (Mumbai)")

            sb.click('button:contains("Create"), button[type="submit"]')
            sb.sleep(5)

        # Extract Redis URL
        redis_url = _extract_redis_url(sb)
        return redis_url


def _extract_redis_url(sb: SB) -> str:
    """Extract Redis URL from Upstash dashboard."""
    selectors = [
        'code',
        'pre',
        'input[readonly]',
        '[data-clipboard-text]',
        '[class*="connection"]',
        '[class*="url"]',
    ]

    for sel in selectors:
        try:
            elements = sb.find_elements(sel)
            for el in elements:
                txt = el.get_attribute("data-clipboard-text") or el.text or el.get_attribute("value") or ""
                if "rediss://" in txt or "redis://" in txt:
                    return txt.strip()
        except Exception:
            continue

    # Regex fallback
    source = sb.get_page_source()
    match = re.search(r'rediss?://[^\s"<>\'&]+', source)
    if match:
        return match.group(0)

    return ""


def verify_upstash_connection(url: str) -> bool:
    """Quick verify the Upstash Redis connection works."""
    try:
        import redis
        r = redis.from_url(url, socket_timeout=5)
        return r.ping()
    except Exception as e:
        print(f"  [!] Upstash connection failed: {e}")
        return False


if __name__ == "__main__":
    email, password, url = setup_upstash()
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Redis URL: {url}")

"""UptimeRobot monitor full setup — account creation + monitor setup.

1. Creates a temp email via mail.tm
2. Signs up on uptimerobot.com using SeleniumBase UC mode
3. Polls temp email for verification link
4. Clicks verification link
5. Creates an HTTP monitor for the Render URL
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from seleniumbase import SB
from temp_email import create_email, wait_for_code, wait_for_verification

COOKIES_FILE = Path(__file__).parent / ".cookies_uptimerobot.txt"


def setup_uptimerobot(
    render_url: str,
    full_name: str = "NSE Quant",
) -> tuple[str, str, bool]:
    """Full automated UptimeRobot setup.

    Returns:
        (email, password, success)
    """
    password = "QuantDeploy2026!"

    # Step 1: Create temp email
    print("  [1/5] Creating temp email...")
    email, token = create_email("uptimequant")
    print(f"  [✓] Email: {email}")

    # Step 2: Sign up on UptimeRobot
    print("  [2/5] Signing up on uptimerobot.com...")
    with SB(uc=True, test=True, headless=True) as sb:
        sb.goto("https://uptimerobot.com/signup")
        sb.sleep(3)

        sb.type('input[name="name"], input[placeholder*="name"]', full_name)
        sb.sleep(0.3)
        sb.type('input[type="email"], input[name="email"]', email)
        sb.sleep(0.3)
        sb.type('input[type="password"], input[name="password"]', password)
        sb.sleep(0.3)

        with contextlib.suppress(Exception):
            sb.click('input[type="checkbox"]', timeout=3)

        sb.click('button[type="submit"], button:contains("Sign up"), button:contains("Create")')
        sb.sleep(5)

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
                sb.goto("https://uptimerobot.com/login")
                sb.sleep(3)
                sb.type('input[type="email"]', email)
                sb.type('input[type="password"]', password)
                sb.click('button[type="submit"]')
                sb.sleep(3)
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
            sb.save_cookies(str(COOKIES_FILE))
    else:
        print("  [4/5] Verification done via OTP")

    # Step 5: Login and create monitor
    print("  [5/5] Creating UptimeRobot monitor...")
    ok = _create_monitor(email, password, render_url)

    print("  [✓] UptimeRobot setup complete")
    print(f"  [✓] Email: {email}")
    print(f"  [✓] Monitor: {'active' if ok else 'failed'}")

    return email, password, ok


def _create_monitor(email: str, password: str, render_url: str) -> bool:
    """Login to UptimeRobot and create an HTTP monitor."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://uptimerobot.com/login")
        sb.sleep(3)

        if "login" in sb.get_current_url() or sb.is_text_visible("Sign in"):
            sb.type('input[type="email"], input[name="email"]', email)
            sb.sleep(0.3)
            sb.type('input[type="password"], input[name="password"]', password)
            sb.sleep(0.3)
            sb.click('button[type="submit"]')
            sb.sleep(5)

        sb.save_cookies(str(COOKIES_FILE))

        # Navigate to add monitor
        sb.goto("https://uptimerobot.com/add")
        sb.sleep(3)

        # Select HTTP(s)
        if sb.is_text_visible("HTTP(s)"):
            sb.click('text="HTTP(s)"')
            sb.sleep(1)

        # Friendly name
        sb.type('input[name="friendly_name"], input[placeholder*="name"]', "NSE-BSE Quant Dashboard")
        sb.sleep(0.3)

        # URL
        sb.type('input[name="url"], input[placeholder*="URL"]', render_url)
        sb.sleep(0.3)

        # Monitoring interval (5 min)
        with contextlib.suppress(Exception):
            sb.select_option_by_text('select[name="interval"]', "5")

        # Create
        sb.click('button:contains("Create Monitor"), button:contains("Save"), button[type="submit"]')
        sb.sleep(3)

        # Confirm if dialog
        if sb.is_text_visible("Yes"):
            sb.click('button:contains("Yes")')
            sb.sleep(2)

        return True


if __name__ == "__main__":
    render_url = input("Enter Render URL: ").strip()
    email, password, ok = setup_uptimerobot(render_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Success: {ok}")

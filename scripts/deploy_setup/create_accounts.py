"""Create accounts on all 5 platforms (Phase 1).

Opens a visible browser so the user can complete CAPTCHAs manually.
After signup, saves credentials for Phase 2 (full automation).

Usage:
    python3 create_accounts.py
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from seleniumbase import SB
from temp_email import create_email

RESULTS_FILE = Path(__file__).parent / "deploy_results.json"
CREDS_FILE = Path(__file__).parent / "accounts.json"


def create_accounts() -> dict:
    """Open browser for user to create accounts on all platforms.

    Uses temp email for each platform. User completes CAPTCHAs manually.
    Returns dict with emails/passwords for each platform.
    """
    password = "QuantDeploy2026!"
    accounts = {}

    print("=" * 60)
    print("  Phase 1: Create Accounts (manual CAPTCHA solving)")
    print("=" * 60)
    print()
    print("  A browser window will open for each platform.")
    print("  Complete any CAPTCHAs that appear, then close the window.")
    print("  The script will continue automatically.")
    print()

    # ── Neon ─────────────────────────────────────────────────────────
    print("━" * 60)
    print("  Creating Neon account...")
    print("━" * 60)
    try:
        email, token = create_email("neonacc")
        print(f"  Temp email: {email}")

        with SB(uc=True, test=False, headless=False) as sb:
            sb.uc_gui_click_captcha()
            sb.goto("https://neon.tech/unify?a=2f0e14a5-2829-4374-962e-d10f98c7a412&n=signup")
            sb.sleep(8)

            sb.uc_gui_click_captcha()
            sb.sleep(2)

            with suppress(Exception):
                sb.type('input[name="email"]', email, timeout=5)
            with suppress(Exception):
                sb.type('input[name="password"]', password, timeout=3)
            with suppress(Exception):
                sb.type('input[name="password-confirm"]', password, timeout=3)

            sb.uc_gui_click_captcha()

            with suppress(Exception):
                sb.click('button:contains("Continue"), button[type="submit"]', timeout=5)

            print()
            print("  Complete the CAPTCHA in the browser window.")
            print("  Press Enter here when done...")
            input()

            sb.save_cookies(str(Path(__file__).parent / ".cookies_neon.txt"))

        accounts["neon"] = {"email": email, "password": password, "token": token}
        print(f"  [✓] Neon account created: {email}")
    except Exception as e:
        print(f"  [!] Neon failed: {e}")
    print()

    # ── Upstash ──────────────────────────────────────────────────────
    print("━" * 60)
    print("  Creating Upstash account...")
    print("━" * 60)
    try:
        email, token = create_email("upsacc")
        print(f"  Temp email: {email}")

        with SB(uc=True, test=False, headless=False) as sb:
            sb.uc_gui_click_captcha()
            sb.goto("https://upstash.com/signup")
            sb.sleep(8)

            sb.uc_gui_click_captcha()

            print()
            print("  Complete the signup form and CAPTCHA in the browser.")
            print("  Use this email:", email)
            print("  Use this password:", password)
            print("  Press Enter when done...")
            input()

            sb.save_cookies(str(Path(__file__).parent / ".cookies_upstash.txt"))

        accounts["upstash"] = {"email": email, "password": password, "token": token}
        print(f"  [✓] Upstash account created: {email}")
    except Exception as e:
        print(f"  [!] Upstash failed: {e}")
    print()

    # ── GitHub ───────────────────────────────────────────────────────
    print("━" * 60)
    print("  Creating GitHub account...")
    print("━" * 60)
    try:
        email, token = create_email("ghacc")
        print(f"  Temp email: {email}")

        with SB(uc=True, test=False, headless=False) as sb:
            sb.uc_gui_click_captcha()
            sb.goto("https://github.com/signup")
            sb.sleep(8)

            sb.uc_gui_click_captcha()

            print()
            print("  Complete the signup form and CAPTCHA in the browser.")
            print("  Use this email:", email)
            print("  Use this password:", password)
            print("  Press Enter when done...")
            input()

            sb.save_cookies(str(Path(__file__).parent / ".cookies_github.txt"))

        accounts["github"] = {"email": email, "password": password, "token": token}
        print(f"  [✓] GitHub account created: {email}")
    except Exception as e:
        print(f"  [!] GitHub failed: {e}")
    print()

    # ── Render ───────────────────────────────────────────────────────
    print("━" * 60)
    print("  Creating Render account...")
    print("━" * 60)
    try:
        email, token = create_email("rendacc")
        print(f"  Temp email: {email}")

        with SB(uc=True, test=False, headless=False) as sb:
            sb.uc_gui_click_captcha()
            sb.goto("https://dashboard.render.com/register")
            sb.sleep(8)

            sb.uc_gui_click_captcha()

            print()
            print("  Complete the signup form and CAPTCHA in the browser.")
            print("  Use this email:", email)
            print("  Use this password:", password)
            print("  Press Enter when done...")
            input()

            sb.save_cookies(str(Path(__file__).parent / ".cookies_render.txt"))

        accounts["render"] = {"email": email, "password": password, "token": token}
        print(f"  [✓] Render account created: {email}")
    except Exception as e:
        print(f"  [!] Render failed: {e}")
    print()

    # ── UptimeRobot ──────────────────────────────────────────────────
    print("━" * 60)
    print("  Creating UptimeRobot account...")
    print("━" * 60)
    try:
        email, token = create_email("uracc")
        print(f"  Temp email: {email}")

        with SB(uc=True, test=False, headless=False) as sb:
            sb.uc_gui_click_captcha()
            sb.goto("https://uptimerobot.com/signup")
            sb.sleep(8)

            sb.uc_gui_click_captcha()

            print()
            print("  Complete the signup form and CAPTCHA in the browser.")
            print("  Use this email:", email)
            print("  Use this password:", password)
            print("  Press Enter when done...")
            input()

            sb.save_cookies(str(Path(__file__).parent / ".cookies_uptimerobot.txt"))

        accounts["uptimerobot"] = {"email": email, "password": password, "token": token}
        print(f"  [✓] UptimeRobot account created: {email}")
    except Exception as e:
        print(f"  [!] UptimeRobot failed: {e}")
    print()

    # Save accounts
    CREDS_FILE.write_text(json.dumps(accounts, indent=2))
    print(f"  Accounts saved to: {CREDS_FILE}")
    print()
    print("=" * 60)
    print("  Phase 1 Complete! Run Phase 2 next:")
    print("  python3 run_all.py")
    print("=" * 60)

    return accounts


if __name__ == "__main__":
    create_accounts()

"""Render web service full setup — account creation + Docker service deployment.

1. Creates a temp email via mail.tm
2. Signs up on render.com using SeleniumBase UC mode
3. Polls temp email for verification link
4. Clicks verification link
5. Creates a Docker web service from the GitHub repo
6. Sets environment variables (PG_DSN, REDIS_URL, REDIS_TTL)
7. Triggers first deploy
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from seleniumbase import SB
from temp_email import create_email, wait_for_code, wait_for_verification

COOKIES_FILE = Path(__file__).parent / ".cookies_render.txt"
REPO_URL = "https://github.com/kondaiahpola1-wq/NSE-BSE-Event-Driven-Quant-Research-Platform"


def setup_render(
    pg_dsn: str,
    redis_url: str,
    full_name: str = "NSE Quant",
    service_name: str = "nse-bse-quant",
) -> tuple[str, str, str]:
    """Full automated Render setup.

    Returns:
        (email, password, render_url)
    """
    password = "QuantDeploy2026!"

    # Step 1: Create temp email
    print("  [1/6] Creating temp email...")
    email, token = create_email("renderquant")
    print(f"  [✓] Email: {email}")

    # Step 2: Sign up on Render
    print("  [2/6] Signing up on render.com...")
    with SB(uc=True, test=True, headless=True) as sb:
        sb.goto("https://dashboard.render.com/register")
        sb.sleep(3)

        # Fill signup form
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
    print("  [3/6] Waiting for verification email (max 5 min)...")
    verify_url = wait_for_verification(token, timeout=300, poll_interval=5)

    if not verify_url:
        otp = wait_for_code(token, timeout=300, poll_interval=5)
        if otp:
            print(f"  [✓] Got OTP: {otp}")
            with SB(uc=True, test=True, headless=True) as sb:
                if COOKIES_FILE.exists():
                    sb.load_cookies(str(COOKIES_FILE))
                sb.goto("https://dashboard.render.com/signin")
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
        print("  [4/6] Clicking verification link...")
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
        print("  [4/6] Verification done via OTP")

    # Step 5: Login and create web service
    print("  [5/6] Creating Render web service...")
    render_url = _create_web_service(email, password, pg_dsn, redis_url, service_name)

    # Step 6: Set env vars and deploy
    print("  [6/6] Setting environment variables...")
    _set_env_vars(email, password, pg_dsn, redis_url, service_name)

    print("  [✓] Render setup complete")
    print(f"  [✓] Email: {email}")
    print(f"  [✓] URL: {render_url}")

    return email, password, render_url


def _create_web_service(
    email: str,
    password: str,
    pg_dsn: str,
    redis_url: str,
    service_name: str,
) -> str:
    """Login to Render and create a Docker web service."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://dashboard.render.com/signin")
        sb.sleep(3)

        if "signin" in sb.get_current_url() or sb.is_text_visible("Sign in"):
            sb.type('input[type="email"], input[name="email"]', email)
            sb.sleep(0.3)
            sb.type('input[type="password"], input[name="password"]', password)
            sb.sleep(0.3)
            sb.click('button[type="submit"]')
            sb.sleep(5)

        sb.save_cookies(str(COOKIES_FILE))

        # New web service
        sb.goto("https://dashboard.render.com/new?type=web")
        sb.sleep(3)

        # Build from Git
        sb.click('text="Build and deploy from a Git repository"')
        sb.sleep(1)
        sb.click('button:contains("Next"), button:contains("Continue")')
        sb.sleep(2)

        # Connect repo
        if sb.is_text_visible("kondaiahpola1-wq"):
            sb.click('text="kondaiahpola1-wq"')
            sb.sleep(1)
        else:
            sb.click('button:contains("Connect a repository"), a:contains("Connect")')
            sb.sleep(3)
            sb.click('text*="NSE-BSE-Event-Driven"')
            sb.sleep(1)

        sb.click('button:contains("Next"), button:contains("Continue")')
        sb.sleep(2)

        # Set service name
        try:
            name_input = sb.find_element('input[name="name"], input[placeholder*="name"]')
            name_input.clear()
            sb.type('input[name="name"], input[placeholder*="name"]', service_name)
        except Exception:
            pass
        sb.sleep(0.5)

        # Region
        with contextlib.suppress(Exception):
            sb.select_option_by_text('select[name="region"]', "Singapore")
        sb.sleep(0.5)

        # Plan: Free
        if sb.is_text_visible("Free"):
            sb.click('text="Free"')
            sb.sleep(0.5)

        # Dockerfile path
        with contextlib.suppress(Exception):
            sb.type('input[name="dockerfilePath"], input[placeholder*="Docker"]', "./Dockerfile")
        sb.sleep(0.5)

        # Create service
        sb.click('button:contains("Create Web Service"), button:contains("Deploy")')
        sb.sleep(5)

        return f"https://{service_name}.onrender.com"


def _set_env_vars(
    email: str,
    password: str,
    pg_dsn: str,
    redis_url: str,
    service_name: str,
) -> None:
    """Set environment variables on the Render service."""
    env_vars = {
        "NSE_QUANT_PG_DSN": pg_dsn,
        "NSE_QUANT_REDIS_URL": redis_url,
        "REDIS_TTL": "3600",
    }

    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto(f"https://dashboard.render.com/web/{service_name}/env")
        sb.sleep(3)

        for key, value in env_vars.items():
            try:
                sb.click('button:contains("Add Environment Variable"), button:contains("Add")')
                sb.sleep(1)

                inputs = sb.find_elements('input[placeholder*="Key"], input[name*="key"]')
                if inputs:
                    inputs[0].clear()
                    sb.send_keys(inputs[0], key)

                val_inputs = sb.find_elements('input[placeholder*="Value"], input[name*="value"]')
                if val_inputs:
                    val_inputs[0].clear()
                    sb.send_keys(val_inputs[0], value)

                sb.click('button:contains("Save"), button:contains("Add")')
                sb.sleep(1)
                print(f"  [✓] Set {key}")
            except Exception as e:
                print(f"  [!] Failed to set {key}: {e}")

    # Trigger deploy
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto(f"https://dashboard.render.com/web/{service_name}/events")
        sb.sleep(3)

        if sb.is_text_visible("Manual Deploy"):
            sb.click('button:contains("Manual Deploy")')
            sb.sleep(1)
            sb.click('text*="Deploy latest commit"')
            sb.sleep(3)
            print("  [✓] Deploy triggered")


if __name__ == "__main__":
    import os
    pg_dsn = os.getenv("NSE_QUANT_PG_DSN", "")
    redis_url = os.getenv("NSE_QUANT_REDIS_URL", "")

    if not pg_dsn or not redis_url:
        print("Set NSE_QUANT_PG_DSN and NSE_QUANT_REDIS_URL first")
        raise SystemExit(1)

    email, password, url = setup_render(pg_dsn, redis_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  URL: {url}")

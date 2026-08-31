"""Neon PostgreSQL full setup — account creation + project setup.

1. Creates a temp email via mail.tm
2. Signs up on neon.tech using SeleniumBase UC mode
3. Polls temp email for verification link
4. Clicks verification link
5. Logs in and creates a project
6. Extracts the PostgreSQL connection string
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from seleniumbase import SB
from temp_email import create_email, wait_for_code, wait_for_verification

COOKIES_FILE = Path(__file__).parent / ".cookies_neon.txt"


def setup_neon(full_name: str = "NSE Quant") -> tuple[str, str, str]:
    """Full automated Neon setup.

    Returns:
        (email_address, password, connection_string)
    """
    password = "QuantDeploy2026!"

    # Step 1: Create temp email
    print("  [1/5] Creating temp email...")
    email, token = create_email("neonquant")
    print(f"  [✓] Email: {email}")

    # Step 2: Sign up on Neon
    print("  [2/5] Signing up on neon.tech...")
    with SB(uc=True, test=True, headless=True) as sb:
        sb.goto("https://console.neon.tech/sign_up")
        sb.sleep(3)

        # Fill signup form
        sb.type('input[name="name"], input[placeholder*="name"], input[name="full_name"]', full_name)
        sb.sleep(0.3)
        sb.type('input[type="email"], input[name="email"]', email)
        sb.sleep(0.3)
        sb.type('input[type="password"], input[name="password"]', password)
        sb.sleep(0.3)

        # Accept terms if checkbox present
        with contextlib.suppress(Exception):
            sb.click('input[type="checkbox"]', timeout=3)

        # Submit
        sb.click('button[type="submit"], button:contains("Sign up"), button:contains("Create")')
        sb.sleep(5)

        # Handle potential Cloudflare/Turnstile challenge
        if sb.is_text_visible("Verify") or sb.is_element_present("iframe"):
            sb.sleep(10)

    # Step 3: Poll for verification email
    print("  [3/5] Waiting for verification email (max 5 min)...")
    verify_url = wait_for_verification(token, timeout=300, poll_interval=5)

    if not verify_url:
        # Try waiting for OTP code instead
        print("  [!] No link found, trying OTP code...")
        otp = wait_for_code(token, timeout=300, poll_interval=5)
        if otp:
            print(f"  [✓] Got OTP: {otp}")
            # Enter OTP in the browser
            with SB(uc=True, test=True, headless=True) as sb:
                if COOKIES_FILE.exists():
                    sb.load_cookies(str(COOKIES_FILE))
                sb.goto("https://console.neon.tech/sign_up")
                sb.sleep(3)
                # Try to find OTP input
                sb.type('input[name="code"], input[placeholder*="code"]', otp)
                sb.click('button[type="submit"], button:contains("Verify")')
                sb.sleep(5)
        else:
            print("  [✗] No verification email received")
            raise RuntimeError("Email verification failed")

    # Step 4: Click verification link
    if verify_url and verify_url.startswith("http"):
        print("  [4/5] Clicking verification link...")
        with SB(uc=True, test=True, headless=True) as sb:
            sb.goto(verify_url)
            sb.sleep(5)

            # Set password if required
            if sb.is_element_present('input[type="password"]'):
                sb.type('input[type="password"]', password)
                sb.sleep(0.3)
                with contextlib.suppress(Exception):
                    sb.click('button[type="submit"]')
                sb.sleep(3)

            sb.save_cookies(str(COOKIES_FILE))
    else:
        print("  [4/5] Verification done via OTP")

    # Step 5: Login and create project
    print("  [5/5] Creating Neon project...")
    neon_dsn = _create_project(email, password, "nse-bse-quant")

    print("  [✓] Neon setup complete")
    print(f"  [✓] Email: {email}")
    print(f"  [✓] DSN: {neon_dsn[:50]}...")

    return email, password, neon_dsn


def _create_project(email: str, password: str, project_name: str) -> str:
    """Login to Neon and create a project, return connection string."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://console.neon.tech/signin")
        sb.sleep(3)

        # Login if needed
        if "signin" in sb.get_current_url() or sb.is_text_visible("Sign in"):
            sb.type('input[type="email"], input[name="email"]', email)
            sb.sleep(0.3)
            sb.type('input[type="password"], input[name="password"]', password)
            sb.sleep(0.3)
            sb.click('button[type="submit"]')
            sb.sleep(5)

        sb.save_cookies(str(COOKIES_FILE))

        # Go to projects
        sb.goto("https://console.neon.tech/app/projects")
        sb.sleep(3)

        # Check if project exists
        if sb.is_text_visible(project_name):
            sb.click(f'text="{project_name}"')
            sb.sleep(3)
        else:
            # Create project
            try:
                sb.click('button:contains("Create project"), a:contains("Create project")')
            except Exception:
                sb.click('a[href*="create"], button:contains("New")')
            sb.sleep(2)

            name_input = sb.find_element('input[name="name"], input[placeholder*="project"]')
            name_input.clear()
            sb.type('input[name="name"], input[placeholder*="project"]', project_name)
            sb.sleep(0.5)
            sb.click('button:contains("Create"), button[type="submit"]')
            sb.sleep(5)

        # Get connection string
        connection_string = _extract_connection_string(sb)

        if not connection_string:
            # Try the dashboard URL approach
            sb.goto("https://console.neon.tech/app/projects")
            sb.sleep(2)
            if sb.is_text_visible(project_name):
                sb.click(f'text="{project_name}"')
                sb.sleep(3)
                connection_string = _extract_connection_string(sb)

        return connection_string


def _extract_connection_string(sb: SB) -> str:
    """Extract PostgreSQL connection string from Neon dashboard."""
    # Try connect button
    try:
        sb.click('button:contains("Connect"), [data-testid="connect-button"]', timeout=5)
        sb.sleep(2)
    except Exception:
        pass

    # Try to find connection string in various places
    selectors = [
        'code',
        'pre',
        '.connection-string',
        '[class*="connection"]',
        '[data-clipboard-text]',
        'input[readonly]',
    ]

    for sel in selectors:
        try:
            elements = sb.find_elements(sel)
            for el in elements:
                txt = el.get_attribute("data-clipboard-text") or el.text or el.get_attribute("value") or ""
                if "postgresql://" in txt:
                    return txt.strip()
        except Exception:
            continue

    # Last resort: regex on page source
    source = sb.get_page_source()
    match = re.search(r'postgresql://[^\s"<>\'&]+', source)
    if match:
        return match.group(0)

    return ""


def verify_neon_connection(dsn: str) -> bool:
    """Quick verify the Neon connection string works."""
    try:
        import sqlalchemy as sa
        engine = sa.create_engine(dsn, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(sa.text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        print(f"  [!] Neon connection failed: {e}")
        return False


if __name__ == "__main__":
    email, password, dsn = setup_neon()
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  DSN: {dsn}")

"""GitHub secrets setup — full PAT creation via SeleniumBase.

1. Creates a temp email via mail.tm
2. Signs up on github.com using SeleniumBase UC mode
3. Polls temp email for verification link
4. Clicks verification link
5. Creates a Personal Access Token (PAT) with repo scope
6. Sets NEON_PG_DSN and UPSTASH_REDIS_URL as repository secrets
"""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path

import httpx
from nacl import public
from seleniumbase import SB
from temp_email import create_email, wait_for_code, wait_for_verification

COOKIES_FILE = Path(__file__).parent / ".cookies_github.txt"
REPO = "kondaiahpola1-wq/NSE-BSE-Event-Driven-Quant-Research-Platform"
API_BASE = "https://api.github.com"


def setup_github_secrets(
    neon_dsn: str,
    redis_url: str,
    full_name: str = "NSE Quant",
    username: str = "kondaiahpola1-wq",
) -> tuple[str, str, bool]:
    """Full automated GitHub setup.

    Returns:
        (email, password, success)
    """
    password = "QuantDeploy2026!Gh"

    # Step 1: Create temp email
    print("  [1/6] Creating temp email...")
    email, token = create_email("ghquant")
    print(f"  [✓] Email: {email}")

    # Step 2: Sign up on GitHub
    print("  [2/6] Signing up on github.com...")
    with SB(uc=True, test=True, headless=True) as sb:
        sb.goto("https://github.com/signup")
        sb.sleep(3)

        # Step through GitHub's multi-step signup
        # Email step
        sb.type('input[type="email"]', email)
        sb.sleep(0.3)
        sb.click('button:contains("Continue"), button[type="submit"]')
        sb.sleep(2)

        # Password step
        sb.type('input[name="password"]', password)
        sb.sleep(0.3)
        sb.click('button:contains("Continue"), button[type="submit"]')
        sb.sleep(2)

        # Username step
        sb.type('input[name="user[login]"]', username)
        sb.sleep(0.3)
        sb.click('button:contains("Continue"), button[type="submit"]')
        sb.sleep(2)

        # Preferences
        try:
            sb.click('button:contains("Continue")', timeout=5)
            sb.sleep(2)
        except Exception:
            pass

        # CAPTCHA / puzzle
        if sb.is_element_present("iframe"):
            sb.sleep(15)

    # Step 3: Poll for verification
    print("  [3/6] Waiting for verification email (max 5 min)...")
    verify_url = wait_for_verification(token, timeout=300, poll_interval=5, sender_contains="github")

    if not verify_url:
        otp = wait_for_code(token, timeout=300, poll_interval=5, sender_contains="github")
        if otp:
            print(f"  [✓] Got OTP: {otp}")
            with SB(uc=True, test=True, headless=True) as sb:
                sb.goto("https://github.com/login")
                sb.sleep(3)
                sb.type('input[type="text"], input[name="login"]', email)
                sb.type('input[type="password"], input[name="password"]', password)
                sb.click('input[type="submit"], button:contains("Sign in")')
                sb.sleep(3)
                sb.type('input[name="otp"], input[autocomplete="one-time-code"]', otp)
                sb.click('input[type="submit"], button:contains("Verify")')
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
            sb.save_cookies(str(COOKIES_FILE))
    else:
        print("  [4/6] Verification done via OTP")

    # Step 5: Create PAT
    print("  [5/6] Creating Personal Access Token...")
    pat = _create_pat(email, password)
    print(f"  [✓] PAT created: {pat[:12]}...")

    # Step 6: Set repo secrets
    print("  [6/6] Setting repository secrets...")
    ok = _set_repo_secrets(pat, neon_dsn, redis_url)

    return email, password, ok


def _create_pat(email: str, password: str) -> str:
    """Create a GitHub Personal Access Token."""
    with SB(uc=True, test=True, headless=True) as sb:
        if COOKIES_FILE.exists():
            sb.load_cookies(str(COOKIES_FILE))

        sb.goto("https://github.com/login")
        sb.sleep(3)

        if "login" in sb.get_current_url() or sb.is_text_visible("Sign in"):
            sb.type('input[type="text"], input[name="login"]', email)
            sb.sleep(0.3)
            sb.type('input[type="password"], input[name="password"]', password)
            sb.sleep(0.3)
            sb.click('input[type="submit"], button:contains("Sign in")')
            sb.sleep(5)

        sb.save_cookies(str(COOKIES_FILE))

        # Go to token settings
        sb.goto("https://github.com/settings/tokens?type=beta")
        sb.sleep(3)

        # Generate new token
        sb.click('button:contains("Generate new token"), a:contains("Generate new token")')
        sb.sleep(2)

        # Note
        sb.type('input[name="name"], input[placeholder*="note"]', "nse-bse-quant-deploy")
        sb.sleep(0.3)

        # Expiration
        with contextlib.suppress(Exception):
            sb.select_option_by_text('select[name="expiration"]', "90 days")
        sb.sleep(0.3)

        # Select repo scope
        try:
            sb.click('text="repo"', timeout=3)
        except Exception:
            # Try checkbox approach
            checkboxes = sb.find_elements('input[type="checkbox"]')
            if checkboxes:
                checkboxes[0].click()
        sb.sleep(0.3)

        # Generate
        sb.click('button:contains("Generate token"), button[type="submit"]')
        sb.sleep(3)

        # Extract token
        token_el = sb.find_element('code, [data-clipboard-text], input[readonly]')
        if token_el:
            pat = token_el.get_attribute("data-clipboard-text") or token_el.text or token_el.get_attribute("value") or ""
            if pat.startswith("ghp_") or pat.startswith("github_pat_"):
                return pat.strip()

    return ""


def _set_repo_secrets(pat: str, neon_dsn: str, redis_url: str) -> bool:
    """Set repository secrets using GitHub API + NaCl encryption."""
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}

    # Get repo public key
    r = httpx.get(f"{API_BASE}/repos/{REPO}/actions/secrets/public-key", headers=headers)
    if r.status_code != 200:
        print(f"  [!] Failed to get repo public key: {r.status_code}")
        return False

    key_data = r.json()
    key_b64 = key_data["key"]
    key_id = key_data["key_id"]

    # Decrypt and re-encrypt for GitHub
    repo_key = public.PublicKey(base64.b64decode(key_b64), encoder=public.Encoder.BOX)
    sealed_box = public.SealedBox(repo_key)

    secrets = {
        "NEON_PG_DSN": neon_dsn,
        "UPSTASH_REDIS_URL": redis_url,
    }

    all_ok = True
    for secret_name, secret_value in secrets.items():
        encrypted = base64.b64encode(sealed_box.encrypt(secret_value.encode())).decode()

        r = httpx.put(
            f"{API_BASE}/repos/{REPO}/actions/secrets/{secret_name}",
            headers=headers,
            json={
                "encrypted_value": encrypted,
                "key_id": key_id,
            },
        )

        if r.status_code in (200, 204):
            print(f"  [✓] Secret {secret_name} set")
        else:
            print(f"  [!] Failed to set {secret_name}: {r.status_code} {r.text[:200]}")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    import os
    neon_dsn = os.getenv("NSE_QUANT_PG_DSN", "")
    redis_url = os.getenv("NSE_QUANT_REDIS_URL", "")

    if not neon_dsn or not redis_url:
        print("Set NSE_QUANT_PG_DSN and NSE_QUANT_REDIS_URL first")
        raise SystemExit(1)

    email, password, ok = setup_github_secrets(neon_dsn, redis_url)
    print(f"\n  Email: {email}")
    print(f"  Password: {password}")
    print(f"  Success: {ok}")

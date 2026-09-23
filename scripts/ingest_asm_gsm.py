"""Scrape NSE ASM/GSM surveillance lists and store in PostgreSQL.

Legacy wrapper — delegates to scrape_nse_surveillance.py (SeleniumBase).

Tables:
    surveillance_stocks: Current active surveillance stocks
    surveillance_history: Daily snapshots

Usage:
    python scripts/ingest_asm_gsm.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


def main() -> int:
    print("Delegating to scrape_nse_surveillance.py (SeleniumBase)...")
    r = subprocess.run(
        [str(VENV_PYTHON), "scripts/scrape_nse_surveillance.py", "--save-json", "--ingest-pg"],
        cwd=str(ROOT),
        timeout=300,
    )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())

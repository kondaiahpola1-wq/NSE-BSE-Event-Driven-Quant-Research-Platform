"""Security type classification for Indian equities.

Classifies symbols into: EQUITY, ETF, DEBT, INDEX, SME, UNKNOWN.

ETF detection: symbol contains ETF/BEES or fund house names
DEBT detection: symbol contains GS/SEC/BOND/TBILL or starts with digits
INDEX detection: symbol starts with NIFTY/SENSEX
SME detection: segment = "SME"
EQUITY: everything else with segment = "EQ"
UNKNOWN: segment is not EQ/SME
"""

from __future__ import annotations

import re

# Fund house name patterns (case-insensitive)
ETF_FUND_HOUSES = [
    "ICICI", "HDFC", "SBI", "ADITYA", "MOTILAL", "NIPPON",
    "ABSL", "AXIS", "DSP", "EDELWEISS", "FRANKLIN", "HSBC",
    "IDBI", "IDFC", "IIFL", "INDIABULLS", "KOTAK", "L&T",
    "MIRAE", "QUANT", "SUNDARAM", "TATA", "UTI", "YES",
]

ETF_PATTERNS = re.compile(
    r"ETF|BEES|"
    + "|".join(ETF_FUND_HOUSES),
    re.IGNORECASE,
)

DEBT_PATTERNS = re.compile(
    r"^GS|^TBILL|^T-BILL|SEC\d|BOND\d|NCD\d",
    re.IGNORECASE,
)

INDEX_PATTERNS = re.compile(
    r"^NIFTY|^SENSEX|^BANKNIFTY|^FINNIFTY|^MIDCPNIFTY",
    re.IGNORECASE,
)

# Short codes starting with digits (BSE debt instruments)
DIGIT_START_PATTERN = re.compile(r"^\d{2}[A-Z]{3,5}$")


def classify_security_type(symbol: str, segment: str | None = None) -> str:
    """Classify a symbol's security type.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "ICICIPR50")
        segment: Exchange segment (e.g., "EQ", "SME", "FO")

    Returns:
        One of: EQUITY, ETF, DEBT, INDEX, SME, UNKNOWN
    """
    symbol = symbol.upper().strip()
    segment = (segment or "").upper()

    # SME segment override
    if segment == "SME":
        return "SME"

    # Index detection (check before ETF — NIFTYBEES is an ETF that tracks NIFTY)
    if INDEX_PATTERNS.match(symbol):
        return "INDEX"

    # ETF detection
    if ETF_PATTERNS.search(symbol):
        return "ETF"

    # Debt detection
    if DEBT_PATTERNS.match(symbol):
        return "DEBT"

    # Short codes starting with digits (BSE debt)
    if DIGIT_START_PATTERN.match(symbol):
        return "DEBT"

    # Default to EQUITY for EQ segment
    if segment == "EQ" or not segment:
        return "EQUITY"

    return "UNKNOWN"


def classify_all_signals(signals: list[dict]) -> list[dict]:
    """Add security_type to all signal dicts.

    Modifies signals in-place and returns them.
    """
    for s in signals:
        symbol = s.get("symbol", "")
        segment = s.get("segment", "EQ")
        s["security_type"] = classify_security_type(symbol, segment)
    return signals

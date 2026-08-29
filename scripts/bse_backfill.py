"""Backfill BSE bars_1d using multi-source router with fallback cascade.

Cascade: Upstox V3 (26 years) -> bseindia lib -> yfinance (3 months).

Uses SourceRouter for source orchestration and circuit breaker protection.

Usage:
    python scripts/bse_backfill.py              # backfill all BSE stocks
    python scripts/bse_backfill.py --limit 50   # backfill first 50 only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import logging

logger = logging.getLogger(__name__)

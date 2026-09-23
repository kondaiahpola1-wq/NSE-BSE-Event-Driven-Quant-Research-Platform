from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Set

import pandas as pd

WATCHLIST_DIR = Path("/home/ubuntu/Documents/projects/real_investments/watch_list")


def _find_symbol_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        col_s = str(col).strip()
        if col_s.startswith("Symbol"):
            return col_s
    return None


class Watchlist:
    """Reads all Excel watchlist files and provides a set of stock symbols."""

    def __init__(self, watchlist_dir: str | Path = str(WATCHLIST_DIR)):
        self._dir = Path(watchlist_dir)
        self._symbols: Set[str] | None = None

    def load(self) -> Set[str]:
        if self._symbols is not None:
            return self._symbols
        self._symbols = set()
        if not self._dir.exists():
            return self._symbols
        for fpath in sorted(glob.glob(str(self._dir / "*.xlsx"))):
            try:
                df = pd.read_excel(fpath)
            except Exception:
                continue
            sym_col = _find_symbol_column(df)
            if sym_col:
                for val in df[sym_col].dropna():
                    sym = str(val).strip().upper()
                    if sym:
                        self._symbols.add(sym)
        return self._symbols

    @property
    def symbols(self) -> Set[str]:
        return self.load()

    def __contains__(self, symbol: str) -> bool:
        return symbol.strip().upper() in self.symbols

    def __iter__(self):
        return iter(self.symbols)

    def __len__(self) -> int:
        return len(self.symbols)

    def to_list(self) -> list[str]:
        return sorted(self.symbols)
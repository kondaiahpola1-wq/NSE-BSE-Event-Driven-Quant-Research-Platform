from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from indian_quant.adapters.announcements.filter import AnnouncementFilter


@dataclass
class AnnouncementAlphaState:
    """Tracks processed announcements to prevent duplicate paper orders."""

    processed_isins: set[str] = field(default_factory=set)
    processed_symbols: set[str] = field(default_factory=set)
    paper_orders_placed: list[dict] = field(default_factory=list)

    def mark_processed(self, symbol: str, isin: str | None = None) -> None:
        self.processed_symbols.add(symbol.upper())
        if isin:
            self.processed_isins.add(isin)

    def is_processed(self, symbol: str, isin: str | None = None) -> bool:
        if symbol.upper() in self.processed_symbols:
            return True
        if isin and isin in self.processed_isins:
            return True
        return False

    def add_order(self, order: dict) -> None:
        self.paper_orders_placed.append(order)

    def save(self, path: str | None = None) -> None:
        if path:
            import json
            with open(path, "w") as f:
                json.dump(self.__dict__, f, indent=2, default=str)

    def load(self, path: str) -> None:
        import json
        with open(path) as f:
            data = json.load(f)
            self.processed_isins = set(data.get("processed_isins", []))
            self.processed_symbols = set(data.get("processed_symbols", []))
            self.paper_orders_placed = data.get("paper_orders_placed", [])
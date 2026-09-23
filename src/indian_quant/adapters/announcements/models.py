from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AnnouncementCategory(str, Enum):
    ORDER = "Award of Order / Receipt of Order"
    BAGGING = "Bagging/Receiving of orders/contracts"
    RESULTS = "Financial Results"
    BOARD_MEETING = "Board Meeting"
    DIVIDEND = "Dividend"
    PRESS = "Press Release"
    BONUS = "Bonus"
    CAPACITY = "Capacity addition"
    NEW_LISTING = "New Listing"
    PREFERENTIAL = "Preferential Issue"


@dataclass(frozen=True)
class Announcement:
    company: str
    symbol: str
    exchange: str
    category: str
    time: str
    scrip_code: str
    announcement_type: str = ""
    linked_text: str = ""
    published_at: datetime | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class Signal:
    symbol: str
    exchange: str
    scrip_code: str
    category: str
    announcement_type: str
    strength: float
    published_at: datetime | None = None
    notes: str = ""


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    exchange: str
    instrument_key: str
    quantity: int
    price: float
    tag: str = ""
    product: str = "D"
    validity: str = "DAY"
    order_type: str = "LIMIT"
    disclosed_quantity: int = 0
    trigger_price: float = 0.0
    is_amo: bool = False
    slice: bool = False

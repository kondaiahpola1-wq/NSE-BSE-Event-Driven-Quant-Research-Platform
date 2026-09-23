"""Abstract base class for browser automation clients."""

from __future__ import annotations

import abc
from typing import Any


class BaseBrowserClient(abc.ABC):
    """Abstract interface for browser automation tools."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Launch the browser."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Close the browser."""

    @abc.abstractmethod
    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """Navigate to a URL.

        Args:
            url: Target URL
            wait_until: "load", "domcontentloaded", or "networkidle"
        """

    @abc.abstractmethod
    async def get_content(self) -> str:
        """Get page HTML content."""

    @abc.abstractmethod
    async def get_text(self, selector: str | None = None) -> str:
        """Get text content of page or element.

        Args:
            selector: CSS selector. None = entire page.
        """

    @abc.abstractmethod
    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        """Query all matching elements.

        Returns list of dicts with keys: text, html, attributes, inner_text.
        """

    @abc.abstractmethod
    async def evaluate(self, js: str) -> Any:
        """Execute JavaScript in the page context."""

    @abc.abstractmethod
    async def screenshot(self, path: str | None = None) -> bytes | None:
        """Take a screenshot. Returns PNG bytes if path is None."""

    @abc.abstractmethod
    async def intercept_requests(self, pattern: str = "*") -> list[dict]:
        """Intercept network requests matching pattern.

        Returns list of dicts with: url, method, headers, body.
        """

    @abc.abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for an element to appear.

        Returns True if found, False if timed out.
        """

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

"""Browser automation layer for web scraping.

Provides unified interface across Playwright (primary), Camofox (anti-detection),
and Obscura (lightweight) for scraping financial data from Indian market websites.
"""

from indian_quant.browser.scraper import BrowserScraper

__all__ = ["BrowserScraper"]

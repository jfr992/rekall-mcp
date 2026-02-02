"""Crawler: Scrapy-based documentation crawler.

Usage:
    # Via CLI
    python -m crawler.cli --config crawl_config.yaml --output crawled_docs

    # Programmatic
    from crawler.spider import DocsSpider, load_crawl_config

Requires scrapy: pip install scrapy
"""

__version__ = "0.1.0"

# Note: DocsSpider requires scrapy, so we don't import it by default
# to avoid ImportError if scrapy isn't installed

"""Generic Scrapy spider for crawling documentation sites."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import yaml

if TYPE_CHECKING:
    from collections.abc import Generator

try:
    import scrapy
    from scrapy.linkextractors import LinkExtractor
    from scrapy.spiders import CrawlSpider, Rule
except ImportError as e:
    raise ImportError(
        "Scrapy is required for crawling. Install with: pip install memento-mcp[crawler]"
    ) from e


def load_crawl_config(config_path: str | None = None) -> dict:
    """Load crawler configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses CRAWL_CONFIG env var
                    or defaults to crawl_config.yaml

    Returns:
        Configuration dictionary
    """
    if config_path is None:
        config_path = os.environ.get("CRAWL_CONFIG", "crawl_config.yaml")

    path = config_path if os.path.isabs(config_path) else os.path.join(os.getcwd(), config_path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Crawler config not found: {path}")

    with open(path) as f:
        return yaml.safe_load(f)


class DocsSpider(CrawlSpider):
    """Generic spider for crawling documentation sites.

    Configuration is loaded from crawl_config.yaml or specified via
    CRAWL_CONFIG environment variable.
    """

    name = "docs_spider"

    def __init__(self, *args, config_path: str | None = None, **kwargs):
        """Initialize spider with configuration.

        Args:
            config_path: Path to YAML config file
        """
        # Load configuration
        self.config = load_crawl_config(config_path)
        target = self.config.get("target", {})

        # Set spider attributes from config
        self.allowed_domains = target.get("allowed_domains", [])
        self.start_urls = target.get("start_urls", [])
        self.name = target.get("name", "docs_spider")

        # Category patterns from config
        self.category_patterns = target.get("categories", {})

        # Selectors from config
        self.selectors = self.config.get("selectors", {})

        # Build rules dynamically
        deny_patterns = target.get("deny_patterns", [r"\?", r"#"])
        self.rules = (
            Rule(
                LinkExtractor(
                    allow_domains=self.allowed_domains,
                    deny=deny_patterns,
                    unique=True,
                ),
                callback="parse_page",
                follow=True,
            ),
        )

        super().__init__(*args, **kwargs)
        self._compile_rules()

    @classmethod
    def update_settings(cls, settings):
        """Update settings from config."""
        # Try to load config for settings
        try:
            config = load_crawl_config()
            crawler_config = config.get("crawler", {})

            settings.setdefault("ROBOTSTXT_OBEY", crawler_config.get("robotstxt_obey", True))
            settings.setdefault("CONCURRENT_REQUESTS", crawler_config.get("concurrent_requests", 1))
            settings.setdefault("CONCURRENT_REQUESTS_PER_DOMAIN", 1)
            settings.setdefault("DOWNLOAD_DELAY", crawler_config.get("download_delay", 2.0))
            settings.setdefault("RANDOMIZE_DOWNLOAD_DELAY", True)
            settings.setdefault("AUTOTHROTTLE_ENABLED", True)
            settings.setdefault("AUTOTHROTTLE_START_DELAY", 2.0)
            settings.setdefault("AUTOTHROTTLE_MAX_DELAY", 10.0)
            settings.setdefault("AUTOTHROTTLE_TARGET_CONCURRENCY", 0.5)
            settings.setdefault("COOKIES_ENABLED", False)
            settings.setdefault("HTTPCACHE_ENABLED", crawler_config.get("cache_enabled", True))
            settings.setdefault("HTTPCACHE_EXPIRATION_SECS", 604800)  # 7 days
            settings.setdefault("HTTPCACHE_DIR", ".scrapy_cache")
            settings.setdefault("LOG_LEVEL", "INFO")
            settings.setdefault(
                "USER_AGENT",
                crawler_config.get("user_agent", "MementoMCP-DocBot/1.0 (Documentation indexer)"),
            )
            settings.setdefault(
                "ITEM_PIPELINES",
                {
                    "crawler.pipeline.DocumentPipeline": 300,
                },
            )
        except FileNotFoundError:
            # Use defaults if no config
            pass

    def parse_page(self, response: scrapy.http.Response) -> Generator[dict[str, Any], None, None]:
        """Parse a documentation page and extract content."""
        url = response.url

        # Skip non-HTML responses
        content_type = response.headers.get("Content-Type", b"").decode("utf-8", errors="ignore")
        if "text/html" not in content_type:
            return

        # Extract page metadata
        title = self._extract_title(response)
        description = self._extract_description(response)

        # Extract main content
        content = self._extract_content(response)
        if not content or len(content) < 100:
            self.logger.debug(f"Skipping {url} - insufficient content")
            return

        # Extract code examples
        code_examples = self._extract_code_examples(response)

        # Extract breadcrumbs/path
        breadcrumbs = self._extract_breadcrumbs(response)

        # Categorize the page
        category = self._categorize_url(url)

        # Generate document ID
        doc_id = self._generate_doc_id(url)

        yield {
            "id": doc_id,
            "url": url,
            "title": title,
            "description": description,
            "content": content,
            "code_examples": code_examples,
            "breadcrumbs": breadcrumbs,
            "category": category,
            "crawled_at": datetime.now(UTC).isoformat(),
        }

    def _extract_title(self, response: scrapy.http.Response) -> str:
        """Extract page title."""
        # Use selectors from config, or defaults
        selectors = self.selectors.get(
            "title",
            [
                "h1::text",
                "article h1::text",
                "main h1::text",
                "title::text",
            ],
        )

        for selector in selectors:
            title = response.css(selector).get()
            if title:
                title = title.strip()
                # Remove common suffixes
                title = re.sub(r"\s*[|\-–]\s*[^|–-]+$", "", title)
                if title:
                    return title
        return "Untitled"

    def _extract_description(self, response: scrapy.http.Response) -> str:
        """Extract page description."""
        # Try meta description
        description = response.css('meta[name="description"]::attr(content)').get()
        if description:
            return description.strip()

        # Try first paragraph
        first_p = response.css("article p::text, main p::text").get()
        if first_p:
            return first_p.strip()[:300]

        return ""

    def _extract_content(self, response: scrapy.http.Response) -> str:
        """Extract main content text."""
        # Use selectors from config, or defaults
        content_selectors = self.selectors.get(
            "content",
            [
                "article",
                "main",
                ".docs-content",
                ".markdown-body",
                '[role="main"]',
            ],
        )

        for selector in content_selectors:
            content_elem = response.css(selector)
            if content_elem:
                # Remove navigation, headers, footers, scripts
                for remove_selector in [
                    "nav",
                    "header",
                    "footer",
                    "script",
                    "style",
                    ".sidebar",
                    ".toc",
                    ".breadcrumb",
                    ".nav",
                ]:
                    content_elem.css(remove_selector).drop()

                # Get text content
                text_parts = content_elem.css("*::text").getall()
                text = " ".join(part.strip() for part in text_parts if part.strip())

                # Clean up whitespace
                text = re.sub(r"\s+", " ", text).strip()

                if text:
                    return text

        return ""

    def _extract_code_examples(self, response: scrapy.http.Response) -> list[dict[str, str]]:
        """Extract code examples from the page."""
        code_examples = []

        # Find code blocks
        code_blocks = response.css("pre code, pre, .highlight code")

        for block in code_blocks:
            code = block.css("::text").getall()
            code_text = "".join(code).strip()

            if not code_text or len(code_text) < 10:
                continue

            # Try to detect language
            language = self._detect_language(block, code_text)

            code_examples.append({"language": language, "code": code_text})

        return code_examples[:10]  # Limit to 10 examples per page

    def _detect_language(self, block: scrapy.Selector, code: str) -> str:
        """Detect programming language of code block."""
        # Check class for language hint
        classes = block.attrib.get("class", "")

        language_patterns = {
            "yaml": r"language-ya?ml|hljs-ya?ml",
            "json": r"language-json|hljs-json",
            "bash": r"language-bash|language-shell|language-sh|hljs-bash",
            "python": r"language-python|language-py|hljs-python",
            "go": r"language-go|hljs-go",
            "javascript": r"language-javascript|language-js|hljs-javascript",
            "typescript": r"language-typescript|language-ts|hljs-typescript",
            "hcl": r"language-hcl|language-terraform|hljs-hcl",
        }

        for lang, pattern in language_patterns.items():
            if re.search(pattern, classes, re.IGNORECASE):
                return lang

        # Heuristic detection
        if code.startswith("apiVersion:") or "kind:" in code[:100]:
            return "yaml"
        if code.startswith("{") or code.startswith("["):
            return "json"
        if code.startswith("#!") or "sudo " in code or "kubectl " in code:
            return "bash"
        if "def " in code or "import " in code:
            return "python"

        return "text"

    def _extract_breadcrumbs(self, response: scrapy.http.Response) -> list[str]:
        """Extract breadcrumb navigation."""
        breadcrumbs = []

        # Try common breadcrumb selectors
        crumb_selectors = [
            ".breadcrumb a::text",
            "nav[aria-label='breadcrumb'] a::text",
            ".breadcrumbs a::text",
        ]

        for selector in crumb_selectors:
            crumbs = response.css(selector).getall()
            if crumbs:
                breadcrumbs = [c.strip() for c in crumbs if c.strip()]
                break

        # Fallback: parse from URL
        if not breadcrumbs:
            parsed = urlparse(response.url)
            path_parts = [p for p in parsed.path.split("/") if p]
            breadcrumbs = path_parts

        return breadcrumbs

    def _categorize_url(self, url: str) -> str:
        """Categorize page based on URL path."""
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Use categories from config
        for category, patterns in self.category_patterns.items():
            for pattern in patterns:
                if pattern in path:
                    return category

        return "general"

    def _generate_doc_id(self, url: str) -> str:
        """Generate unique document ID from URL."""
        # Normalize URL
        parsed = urlparse(url)
        normalized = f"{parsed.netloc}{parsed.path}".rstrip("/")
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

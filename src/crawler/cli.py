"""CLI for running the documentation crawler."""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    """Main entry point for crawler CLI."""
    parser = argparse.ArgumentParser(
        description="Crawl documentation sites for indexing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Crawl using config file
  python -m crawler.cli --config crawl_config.yaml

  # Crawl with custom output directory
  python -m crawler.cli --config mysite.yaml --output docs/

  # Limit number of pages
  python -m crawler.cli --config mysite.yaml --limit 100
""",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="crawl_config.yaml",
        help="Path to YAML config file (default: crawl_config.yaml)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="crawled_docs",
        help="Output directory for crawled documents (default: crawled_docs)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=0,
        help="Maximum number of pages to crawl (0 = unlimited)",
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        default=2.0,
        help="Delay between requests in seconds (default: 2.0)",
    )
    args = parser.parse_args()

    # Check config file exists
    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}")
        print("Create a config file or specify path with --config")
        sys.exit(1)

    try:
        from scrapy.crawler import CrawlerProcess
    except ImportError:
        print("Error: Scrapy is required. Install with: pip install scrapy")
        sys.exit(1)

    # Set environment variables for spider/pipeline
    os.environ["CRAWL_CONFIG"] = args.config
    os.environ["CRAWL_OUTPUT_DIR"] = args.output

    from crawler.spider import DocsSpider

    # Configure crawler
    settings = {
        "DOWNLOAD_DELAY": args.delay,
        "LOG_LEVEL": "INFO",
        "ITEM_PIPELINES": {
            "crawler.pipeline.DocumentPipeline": 300,
        },
    }

    if args.limit > 0:
        settings["CLOSESPIDER_ITEMCOUNT"] = args.limit

    print(f"Starting crawler with config: {args.config}")
    print(f"Output directory: {args.output}")

    process = CrawlerProcess(settings)
    process.crawl(DocsSpider, config_path=args.config)
    process.start()

    print("Crawl complete!")


if __name__ == "__main__":
    main()

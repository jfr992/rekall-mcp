"""Scrapy pipeline for processing crawled documents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scrapy import Spider


class DocumentPipeline:
    """Pipeline to save crawled documents to JSON files."""

    def __init__(self) -> None:
        # Get output directory from environment or default
        output_dir = os.environ.get("CRAWL_OUTPUT_DIR", "crawled_docs")
        self.output_dir = Path(output_dir)
        self.documents: list[dict[str, Any]] = []

    def open_spider(self, spider: Spider) -> None:
        """Called when spider opens."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        spider.logger.info(f"Saving documents to {self.output_dir.absolute()}")

    def process_item(self, item: dict[str, Any], spider: Spider) -> dict[str, Any]:
        """Process each crawled item."""
        self.documents.append(item)

        # Save individual document
        doc_file = self.output_dir / f"{item['id']}.json"
        doc_file.write_text(json.dumps(item, indent=2))

        spider.logger.info(f"Saved: {item['title'][:50]} ({item['url']})")
        return item

    def close_spider(self, spider: Spider) -> None:
        """Called when spider closes."""
        # Save manifest
        manifest = {
            "total_documents": len(self.documents),
            "documents": [
                {
                    "id": doc["id"],
                    "url": doc["url"],
                    "title": doc["title"],
                    "category": doc["category"],
                }
                for doc in self.documents
            ],
        }

        manifest_file = self.output_dir / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2))

        spider.logger.info(f"Crawl complete. Total documents: {len(self.documents)}")

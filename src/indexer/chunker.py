"""Document chunking for semantic search."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DocumentChunk:
    """A chunk of a document for indexing."""

    doc_id: str
    chunk_id: str
    content: str
    metadata: dict[str, str | int | list[str]]


class DocumentChunker:
    """Chunk documents for vector indexing.

    Splits documents into semantically meaningful chunks that are
    optimal for embedding and retrieval.

    Example:
        chunker = DocumentChunker(chunk_size=512)
        document = {"id": "doc1", "content": "...", "title": "..."}
        chunks = chunker.chunk_document(document)
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100,
    ) -> None:
        """Initialize chunker.

        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Number of characters to overlap between chunks
            min_chunk_size: Minimum chunk size to keep
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_document(self, document: dict) -> list[DocumentChunk]:
        """Split a document into chunks.

        Args:
            document: Document dict with id, content, title, url, etc.

        Returns:
            List of DocumentChunk objects
        """
        chunks = []
        doc_id = document["id"]
        content = document.get("content", "")
        title = document.get("title", "")
        url = document.get("url", "")
        category = document.get("category", "general")

        # First, add title + description as first chunk
        description = document.get("description", "")
        if title or description:
            header_content = f"{title}\n\n{description}".strip()
            if len(header_content) >= self.min_chunk_size:
                chunks.append(
                    DocumentChunk(
                        doc_id=doc_id,
                        chunk_id=f"{doc_id}_header",
                        content=header_content,
                        metadata={
                            "url": url,
                            "title": title,
                            "category": category,
                            "chunk_type": "header",
                        },
                    )
                )

        # Split content into semantic chunks
        content_chunks = self._split_content(content)

        for i, chunk_content in enumerate(content_chunks):
            if len(chunk_content) < self.min_chunk_size:
                continue

            chunks.append(
                DocumentChunk(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}_chunk_{i}",
                    content=chunk_content,
                    metadata={
                        "url": url,
                        "title": title,
                        "category": category,
                        "chunk_type": "content",
                        "chunk_index": i,
                    },
                )
            )

        # Add code examples as separate chunks
        code_examples = document.get("code_examples", [])
        for j, example in enumerate(code_examples):
            code = example.get("code", "")
            language = example.get("language", "text")

            if len(code) < 20:
                continue

            # Add context to code
            code_content = f"Code example ({language}):\n```{language}\n{code}\n```"

            chunks.append(
                DocumentChunk(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}_code_{j}",
                    content=code_content,
                    metadata={
                        "url": url,
                        "title": title,
                        "category": category,
                        "chunk_type": "code",
                        "language": language,
                    },
                )
            )

        return chunks

    def _split_content(self, content: str) -> list[str]:
        """Split content into chunks using semantic boundaries.

        Args:
            content: Raw text content

        Returns:
            List of text chunks
        """
        if not content:
            return []

        # Try to split on semantic boundaries
        # Priority: headers > paragraphs > sentences > words

        # First, try splitting on headers
        header_pattern = r"\n(?=#{1,6}\s|\n[A-Z][^.!?]*:\s*\n)"
        sections = re.split(header_pattern, content)

        chunks = []
        current_chunk = ""

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # If section fits in chunk, add it
            if len(current_chunk) + len(section) + 1 <= self.chunk_size:
                current_chunk = f"{current_chunk}\n{section}".strip()
            else:
                # Save current chunk if big enough
                if len(current_chunk) >= self.min_chunk_size:
                    chunks.append(current_chunk)

                # If section is too big, split it further
                if len(section) > self.chunk_size:
                    sub_chunks = self._split_large_section(section)
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""
                else:
                    current_chunk = section

        # Don't forget the last chunk
        if len(current_chunk) >= self.min_chunk_size:
            chunks.append(current_chunk)

        return chunks

    def _split_large_section(self, section: str) -> list[str]:
        """Split a large section into smaller chunks.

        Args:
            section: Text section to split

        Returns:
            List of smaller chunks
        """
        chunks = []

        # Split on paragraph boundaries
        paragraphs = re.split(r"\n\s*\n", section)

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= self.chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)

                # If paragraph itself is too big, split on sentences
                if len(para) > self.chunk_size:
                    sentence_chunks = self._split_on_sentences(para)
                    chunks.extend(sentence_chunks[:-1])
                    current_chunk = sentence_chunks[-1] if sentence_chunks else ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_on_sentences(self, text: str) -> list[str]:
        """Split text on sentence boundaries.

        Args:
            text: Text to split

        Returns:
            List of text chunks
        """
        # Simple sentence splitting
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 <= self.chunk_size:
                current_chunk = f"{current_chunk} {sentence}".strip()
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

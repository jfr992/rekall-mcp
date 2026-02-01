"""Embeddings: Convert text to vectors for semantic search.

Supports multiple embedding providers:
- sentence-transformers (default, local, free)
- Ollama (local, free, requires Ollama running)
- Gemini (cloud, free tier available)

Usage:
    from core import Embedder

    # Default: sentence-transformers (local)
    embedder = Embedder()

    # Ollama (local, free)
    embedder = Embedder(provider="ollama", model="nomic-embed-text")

    # Gemini (cloud, free tier)
    embedder = Embedder(provider="gemini", api_key="your-key")

    # Single text
    vector = embedder.encode("Hello world")

    # Batch (more efficient)
    vectors = embedder.encode_batch(["Hello", "World"])

    # Check dimensions
    print(embedder.dimensions)  # varies by model

All operations are traced via Telemetry.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from core.telemetry import Telemetry

logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER INTERFACE
# =============================================================================


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return embedding vector dimensions."""
        pass

    @abstractmethod
    def encode(self, text: str) -> list[float]:
        """Encode single text to vector."""
        pass

    @abstractmethod
    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors."""
        pass


# =============================================================================
# PROVIDERS
# =============================================================================


class SentenceTransformerProvider(EmbeddingProvider):
    """Local embeddings using sentence-transformers.

    Pros:
    - Runs entirely local (no API calls)
    - Fast (~80MB model)
    - Free, no rate limits
    - Good quality for general text

    Cons:
    - Uses ~500MB RAM when loaded
    - First load is slow (~5s)
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model: str | None = None, device: str | None = None):
        self.model_name = model or self.DEFAULT_MODEL
        self._device = device
        self._model = None

    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise ImportError(
                    "sentence-transformers required. Install: pip install sentence-transformers"
                ) from e

            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name, device=self._device)
            logger.info(f"Model loaded: {self.dimensions} dimensions")

        return self._model

    @property
    def dimensions(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    def encode(self, text: str) -> list[float]:
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=len(texts) > 100,
            convert_to_numpy=True,
        )
        return embeddings.tolist()


class OllamaProvider(EmbeddingProvider):
    """Local embeddings using Ollama.

    Pros:
    - Runs entirely local (no API calls)
    - Free, no rate limits
    - Many models available (nomic-embed-text, mxbai-embed-large, etc.)
    - Can use GPU if available

    Cons:
    - Requires Ollama running locally
    - Some models are large (>1GB)
    - Slower than sentence-transformers for CPU

    Setup:
        1. Install Ollama: https://ollama.ai
        2. Pull a model: ollama pull nomic-embed-text
        3. Ollama runs on http://localhost:11434 by default
    """

    DEFAULT_MODEL = "nomic-embed-text"  # 768 dimensions, good quality
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "snowflake-arctic-embed": 1024,
    }

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.model_name = model or self.DEFAULT_MODEL
        self.base_url = base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        self._dimensions = self.MODEL_DIMENSIONS.get(self.model_name, 768)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode(self, text: str) -> list[float]:
        import httpx

        response = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model_name, "prompt": text},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        # Ollama doesn't have native batch API, so we loop
        return [self.encode(text) for text in texts]


class GeminiProvider(EmbeddingProvider):
    """Cloud embeddings using Google Gemini API.

    Pros:
    - High quality embeddings
    - Free tier: 1500 requests/day
    - 768 dimensions, good for semantic search

    Cons:
    - Requires API key
    - Network latency
    - Rate limited on free tier

    Setup:
        1. Get API key: https://ai.google.dev/
        2. Set GEMINI_API_KEY environment variable
    """

    DEFAULT_MODEL = "text-embedding-004"  # Latest embedding model

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self.model_name = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY or pass api_key parameter."
            )
        self._dimensions = 768  # Gemini embedding models use 768 dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode(self, text: str) -> list[float]:
        import httpx

        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:embedContent",
            params={"key": self.api_key},
            json={
                "model": f"models/{self.model_name}",
                "content": {"parts": [{"text": text}]},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()["embedding"]["values"]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        import httpx

        # Gemini supports batch embedding
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:batchEmbedContents",
            params={"key": self.api_key},
            json={
                "requests": [
                    {
                        "model": f"models/{self.model_name}",
                        "content": {"parts": [{"text": text}]},
                    }
                    for text in texts
                ]
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return [emb["values"] for emb in response.json()["embeddings"]]


# =============================================================================
# MAIN EMBEDDER CLASS
# =============================================================================


class Embedder:
    """Generate embeddings with configurable provider.

    Wraps embedding providers with:
    - Lazy loading (model loads on first use)
    - Telemetry (all operations tracked)
    - Simple API (encode, encode_batch)

    Providers:
        - "sentence-transformers" (default): Local, free, fast
        - "ollama": Local, free, requires Ollama running
        - "gemini": Cloud, free tier (1500/day), high quality

    Example:
        # Default (local sentence-transformers)
        embedder = Embedder()

        # Ollama
        embedder = Embedder(provider="ollama")

        # Gemini
        embedder = Embedder(provider="gemini")

        vector = embedder.encode("architecture decisions")
    """

    PROVIDERS = {
        "sentence-transformers": SentenceTransformerProvider,
        "ollama": OllamaProvider,
        "gemini": GeminiProvider,
    }

    # Default model: good balance of quality and speed
    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        model: str | None = None,
        device: str | None = None,
        provider: str = "sentence-transformers",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize embedder.

        Args:
            model: Model name (varies by provider)
            device: Device to use (sentence-transformers only)
            provider: "sentence-transformers", "ollama", or "gemini"
            api_key: API key (gemini only)
            base_url: Base URL (ollama only)
        """
        self.provider_name = provider
        self._provider: EmbeddingProvider | None = None
        self._telemetry = Telemetry.get()

        # Store config for lazy initialization
        self._config = {
            "model": model,
            "device": device,
            "api_key": api_key,
            "base_url": base_url,
        }

        # For backwards compatibility
        self.model_name = model or self.DEFAULT_MODEL

    @property
    def provider(self) -> EmbeddingProvider:
        """Get the provider, initializing if needed."""
        if self._provider is None:
            with self._telemetry.track("embedder.load_model"):
                self._provider = self._create_provider()
        return self._provider

    def _create_provider(self) -> EmbeddingProvider:
        """Create the configured provider."""
        provider_cls = self.PROVIDERS.get(self.provider_name)
        if not provider_cls:
            available = ", ".join(self.PROVIDERS.keys())
            raise ValueError(f"Unknown provider: {self.provider_name}. Available: {available}")

        if self.provider_name == "sentence-transformers":
            return provider_cls(
                model=self._config["model"],
                device=self._config["device"],
            )
        elif self.provider_name == "ollama":
            return provider_cls(
                model=self._config["model"],
                base_url=self._config["base_url"],
            )
        elif self.provider_name == "gemini":
            return provider_cls(
                model=self._config["model"],
                api_key=self._config["api_key"],
            )

        raise ValueError(f"Unknown provider: {self.provider_name}")

    # Backwards compatibility: expose model property
    @property
    def model(self):
        """Get the underlying model (sentence-transformers only)."""
        if self.provider_name == "sentence-transformers":
            return self.provider.model
        raise AttributeError(f"model attribute not available for {self.provider_name} provider")

    @property
    def dimensions(self) -> int:
        """Embedding vector dimensions."""
        return self.provider.dimensions

    def encode(self, text: str) -> list[float]:
        """Convert text to embedding vector.

        Args:
            text: Text to encode

        Returns:
            List of floats (embedding vector)
        """
        with self._telemetry.track("embedder.encode"):
            return self.provider.encode(text)

    def encode_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float]]:
        """Convert multiple texts to embeddings.

        Args:
            texts: List of texts
            batch_size: Batch size (sentence-transformers only)
            show_progress: Show progress bar (sentence-transformers only)

        Returns:
            List of embedding vectors
        """
        with self._telemetry.track("embedder.encode_batch"):
            return self.provider.encode_batch(texts)

    def __repr__(self) -> str:
        loaded = "loaded" if self._provider else "not loaded"
        return f"Embedder(provider={self.provider_name}, {loaded})"


# =============================================================================
# COMPARISON GUIDE
# =============================================================================

PROVIDER_COMPARISON = """
Embedding Provider Comparison
=============================

| Provider            | Location | Cost      | Speed   | Quality | Dimensions |
|---------------------|----------|-----------|---------|---------|------------|
| sentence-transformers| Local   | Free      | Fast    | Good    | 384        |
| Ollama              | Local    | Free      | Medium  | Good+   | 768-1024   |
| Gemini              | Cloud    | Free tier | Slow*   | Best    | 768        |

* Slow due to network latency

Recommendations:
- Development/Testing: sentence-transformers (fastest setup)
- Production (local): Ollama with nomic-embed-text (good quality, no API costs)
- Production (cloud): Gemini (highest quality, free tier may suffice)

Free Tiers:
- sentence-transformers: Unlimited (local)
- Ollama: Unlimited (local)
- Gemini: 1,500 requests/day

Setup Commands:
- sentence-transformers: pip install sentence-transformers
- Ollama: brew install ollama && ollama pull nomic-embed-text
- Gemini: Get API key at https://ai.google.dev/
"""

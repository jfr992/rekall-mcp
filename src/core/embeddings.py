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
from collections import OrderedDict

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


class FastEmbedProvider(EmbeddingProvider):
    """Local embeddings using fastembed (ONNX, no torch).

    Vector-identical to SentenceTransformerProvider for the canonical model
    (fp32 ONNX export of the same weights) — see tests/test_fastembed_identity.py.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    _CANONICAL = {"all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2"}

    def __init__(self, model: str | None = None) -> None:
        from fastembed import TextEmbedding

        self.model_name = model or self.DEFAULT_MODEL
        self._model = TextEmbedding(
            model_name=self._CANONICAL.get(self.model_name, self.model_name)
        )
        if self.model_name == "all-MiniLM-L6-v2":
            # sentence-transformers truncates at max_seq_length=256; fastembed's
            # tokenizer config says 128 — align or long docs embed differently.
            self._model.model.tokenizer.enable_truncation(max_length=256)

    @property
    def dimensions(self) -> int:
        return 384

    def encode(self, text: str) -> list[float]:
        return list(next(iter(self._model.embed([text]))))

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._model.embed(texts)]


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
        # Ollama doesn't have native batch API — parallelize with threads
        from concurrent.futures import ThreadPoolExecutor

        workers = min(8, len(texts)) if texts else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self.encode, texts))


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
        "fastembed": FastEmbedProvider,
        "ollama": OllamaProvider,
        "gemini": GeminiProvider,
    }

    # Default model: good balance of quality and speed
    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        model: str | None = None,
        device: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Initialize embedder.

        Args:
            model: Model name (varies by provider)
            device: Device to use (sentence-transformers only)
            provider: "sentence-transformers", "fastembed", "ollama", or "gemini".
                None = resolve from EMBEDDING_PROVIDER env, then auto-detect
                (fastembed if importable — the packaged default — else
                sentence-transformers).
            api_key: API key (gemini only)
            base_url: Base URL (ollama only)
        """
        self.provider_name = self._resolve_provider_name(provider)
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

        # Embedding cache (avoids redundant model calls for repeated text)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_max = 512

    @staticmethod
    def _resolve_provider_name(requested: str | None) -> str:
        """EMBEDDING_PROVIDER=fastembed wins; explicit request keeps today's; auto prefers fastembed."""
        env = os.environ.get("EMBEDDING_PROVIDER", "").strip()
        if env == "fastembed":
            return "fastembed"
        if requested:
            return requested
        if env:
            return env
        import importlib.util

        if importlib.util.find_spec("fastembed") is not None:
            return "fastembed"
        return "sentence-transformers"

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
        elif self.provider_name == "fastembed":
            return provider_cls(model=self._config["model"])
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

    @property
    def dimensions(self) -> int:
        """Embedding vector dimensions."""
        return self.provider.dimensions

    def encode(self, text: str) -> list[float]:
        """Convert text to embedding vector.

        Results are cached (up to 512 entries) to avoid redundant model calls.

        Args:
            text: Text to encode

        Returns:
            List of floats (embedding vector)
        """
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]

        with self._telemetry.track("embedder.encode"):
            result = self.provider.encode(text)

        self._cache[text] = result
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return result

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

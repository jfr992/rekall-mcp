"""Identity invariant: fastembed vectors match sentence-transformers (fp32 ONNX).

Skips when the [torch] extra is absent — fastembed-only environments
(the packaged default) rely on CI's embedder-identity job for this guarantee.
"""

import math

import pytest

pytest.importorskip("sentence_transformers")

from core.embeddings import FastEmbedProvider, SentenceTransformerProvider

# question + seed-memory summary strings copied verbatim from
# benchmarks/eval/probes/core.frozen.json (pr-01, er-01) — corpus untouched.
PR_01_QUESTION = "How do I prefer error handling in Go services?"
PR_01_SUMMARY = (
    "Prefers wrapped sentinel errors with %w and errors.Is; "
    "house rule: every service error must wrap the base sentinel ErrKestrel."
)
ER_01_QUESTION = "What port does our internal metrics proxy listen on?"
ER_01_SUMMARY = (
    "Decided the internal metrics proxy listens on port 9741 to avoid the 9090 Prometheus clash."
)
LONG_DOC = " ".join(f"token{i} committed the change because reason {i}" for i in range(80))

TEXTS = [PR_01_QUESTION, PR_01_SUMMARY, ER_01_QUESTION, ER_01_SUMMARY, LONG_DOC]

TOLERANCE = 0.9999


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_fastembed_identical_to_sentence_transformers():
    st = SentenceTransformerProvider(model="all-MiniLM-L6-v2")
    fe = FastEmbedProvider(model="all-MiniLM-L6-v2")

    for text in TEXTS:
        cos = _cos(st.encode(text), fe.encode(text))
        assert cos >= TOLERANCE, f"cosine {cos:.6f} < {TOLERANCE} for text: {text[:60]!r}"

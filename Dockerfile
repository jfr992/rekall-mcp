# Rekall MCP - Docker Image (all-in-one)
#
# Build:
#   docker build -t rekall-mcp .
#
# Run (embedded Qdrant, named volume):
#   docker run -d -v rekall-data:/data -p 127.0.0.1:8000:8000 rekall-mcp
#
# Run against an external Qdrant:
#   docker run -d -v rekall-data:/data -p 127.0.0.1:8000:8000 \
#     -e QDRANT_URL=http://host.docker.internal:6333 rekall-mcp

FROM python:3.11-slim AS base

WORKDIR /app

# gosu: entrypoint starts as root to chown /data, then drops to mcp
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Copy dependency files first for better layer caching
COPY pyproject.toml README.md ./

# Prod deps only — fastembed is ONNX-based, no torch needed
RUN uv pip install --system -r pyproject.toml

COPY src/ src/

RUN useradd --create-home --shell /bin/bash mcp \
    && mkdir -p /data/memory /data/qdrant \
    && chown -R mcp:mcp /data

# Bake the embedding model into the image. fastembed 0.8 exposes no HF
# revision parameter (download_model always resolves the repo's current sha),
# so the practical pin is this immutable layer: runtime loads cache-first and
# never re-downloads. See PLAN.md Task 5 note.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/fastembed_cache

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Default environment. QDRANT_PATH/QDRANT_URL deliberately unset here:
# entrypoint.sh defaults QDRANT_PATH=/data/qdrant only when QDRANT_URL is
# absent (compose sets QDRANT_URL; both set trips the mutual-exclusion guard).
ENV PYTHONPATH=/app/src
ENV MCP_TRANSPORT=streamable-http
ENV EMBEDDING_PROVIDER=fastembed
ENV MEMORY_STORAGE_PATH=/data/memory
ENV HOST=0.0.0.0
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Root at start: entrypoint chowns /data (named volumes arrive root-owned),
# then drops to mcp via gosu.
USER root
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "server"]

# Test image (compose --profile test): prod image + dev deps
# jq: the shipped hooks (claude/hooks/*.sh) pipe through it; hook tests need it
FROM base AS test
RUN apt-get update && apt-get install -y --no-install-recommends jq && rm -rf /var/lib/apt/lists/*
RUN uv pip install --system -r pyproject.toml --extra dev

# Default build target = prod image
FROM base

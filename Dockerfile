# Memento MCP - Docker Image
#
# Build:
#   docker build -t memento-mcp .
#
# Run:
#   docker run -p 8000:8000 \
#     -e QDRANT_URL=http://host.docker.internal:6333 \
#     -e MCP_TRANSPORT=streamable-http \
#     -e HOST=0.0.0.0 \
#     memento-mcp

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first for better layer caching
COPY pyproject.toml README.md ./

# Install dependencies (includes sentence-transformers for embeddings)
RUN uv pip install --system -e ".[dev]"

# Copy source code
COPY src/ src/
COPY tests/ tests/

# Create non-root user
RUN useradd --create-home --shell /bin/bash mcp \
    && mkdir -p /home/mcp/.claude/memory \
    && chown -R mcp:mcp /home/mcp

USER mcp

# Pre-download the default embedding model (saves time on first run)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 8000

# Default environment
ENV PYTHONPATH=/app/src
ENV MCP_TRANSPORT=streamable-http
ENV EMBEDDING_PROVIDER=sentence-transformers
ENV HOST=0.0.0.0
ENV PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "server"]

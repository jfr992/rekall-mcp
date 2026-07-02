.PHONY: install dev test lint format typecheck clean docker-build docker-run docker-test help backup

# Default target
help:
	@echo "Rekall MCP - Development Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Basic Commands:"
	@echo "  install        Install dependencies"
	@echo "  dev            Install with dev dependencies"
	@echo "  test           Run tests"
	@echo "  test-html      Run tests with HTML coverage report"
	@echo "  lint           Run linter"
	@echo "  format         Format code"
	@echo "  typecheck      Run type checker"
	@echo "  clean          Clean build artifacts"
	@echo ""
	@echo "Memory Commands:"
	@echo "  memory-stats   Show memory storage statistics"
	@echo "  memory-clean   Clean up old memory files (interactive)"
	@echo "  backup         Tarball ~/.claude/memory + Qdrant volume to ~/backups"
	@echo "  qdrant         Start Qdrant vector database"
	@echo "  qdrant-stop    Stop Qdrant"
	@echo ""
	@echo "Docker Commands:"
	@echo "  docker-build   Build Docker image"
	@echo "  docker-run     Run MCP server in Docker"
	@echo "  docker-dev     Run with live reload"
	@echo "  docker-test    Run tests in Docker"
	@echo "  docker-clean   Stop and remove all containers"
	@echo ""
	@echo "Server Commands:"
	@echo "  run            Run MCP server locally (stdio)"
	@echo "  run-http       Run MCP server with HTTP transport"
	@echo ""
	@echo "Quick Start:"
	@echo "  1. make qdrant         # Start vector database"
	@echo "  2. make dev            # Install dependencies"
	@echo "  3. make run            # Start MCP server"

# Installation
install:
	uv pip install -e .

dev:
	uv pip install -e ".[dev]"

# Testing
test:
	pytest -v --cov=src --cov-report=term-missing

test-html:
	pytest -v --cov=src --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

test-e2e:
	pytest tests/test_e2e_memory.py -v

test-memory:
	pytest tests/test_memory.py tests/test_memory_cli.py -v

# Code quality
lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check src/ tests/ --fix

typecheck:
	mypy src/

# Pre-commit
pre-commit:
	pre-commit install
	pre-commit run --all-files

# =============================================================================
# MEMORY COMMANDS
# =============================================================================

# Show memory storage statistics
memory-stats:
	@echo "Memory storage statistics:"
	@python -c "from pathlib import Path; import os; \
	    mem_dir = Path.home() / '.claude' / 'memory'; \
	    if mem_dir.exists(): \
	        files = list(mem_dir.glob('*.yaml')); \
	        total_size = sum(f.stat().st_size for f in files); \
	        print(f'  Files: {len(files)}'); \
	        print(f'  Size: {total_size / 1024:.1f} KB'); \
	        print(f'  Location: {mem_dir}'); \
	    else: \
	        print(f'  No memory directory found at {mem_dir}');"

# Clean up old memory files (interactive)
memory-clean:
	@python -m memory.cli cleanup --interactive

# Start Qdrant vector database
qdrant:
	@echo "Starting Qdrant vector database..."
	docker compose up -d qdrant
	@echo "Qdrant running at http://localhost:6333"
	@echo "Dashboard at http://localhost:6333/dashboard"

qdrant-stop:
	docker compose stop qdrant

backup:
	@mkdir -p ~/backups
	@TS=$$(date +%Y%m%d-%H%M%S); \
	tar czf ~/backups/pre-$$TS-memory.tar.gz -C ~ .claude/memory; \
	docker compose stop qdrant; \
	tar czf ~/backups/pre-$$TS-qdrant.tar.gz -C ~/.claude qdrant; \
	docker compose start qdrant; \
	echo "Backups written: ~/backups/pre-$$TS-{memory,qdrant}.tar.gz"

# =============================================================================
# DOCKER COMMANDS
# =============================================================================

docker-build:
	docker compose build

docker-run:
	docker compose up mcp

docker-dev:
	docker compose --profile dev up mcp-dev

docker-test:
	docker compose --profile test run --rm test

docker-clean:
	docker compose down -v

# =============================================================================
# SERVER COMMANDS
# =============================================================================

# Run server locally with stdio transport
run:
	python -m server

# Run server with HTTP transport
run-http:
	MCP_TRANSPORT=streamable-http python -m server

# =============================================================================
# CLEANUP
# =============================================================================

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf coverage/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

clean-memory:
	@echo "WARNING: This will delete all memory files!"
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read dummy && rm -rf ~/.claude/memory/*.yaml

clean-all: clean docker-clean
	@echo "Cleaned all build artifacts and Docker containers"

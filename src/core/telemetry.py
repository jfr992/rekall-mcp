"""Observability: OTEL metrics and tracing for all core operations.

Usage:
    from core.telemetry import Telemetry

    # Get the singleton
    telemetry = Telemetry.get()

    # Track operations
    with telemetry.track("vector_store.save"):
        store.save(...)

    # Or use decorators
    @telemetry.traced("embedder.encode")
    def encode(text): ...

    # Export metrics
    telemetry.get_metrics()  # Returns dict for Prometheus/Grafana
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# METRICS: What we measure
# =============================================================================


@dataclass
class OperationMetrics:
    """Metrics for a single operation type.

    Tracks count, latency distribution, and errors.
    """

    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    durations_ms: list[float] = field(default_factory=list)

    # Keep last N for percentile calculation
    MAX_SAMPLES = 1000

    def record(self, duration_ms: float, success: bool = True) -> None:
        """Record one operation."""
        self.count += 1
        if not success:
            self.errors += 1

        self.total_duration_ms += duration_ms
        self.durations_ms.append(duration_ms)

        # Trim to avoid memory growth
        if len(self.durations_ms) > self.MAX_SAMPLES:
            self.durations_ms = self.durations_ms[-self.MAX_SAMPLES :]

    @property
    def avg_ms(self) -> float:
        """Average latency in milliseconds."""
        return self.total_duration_ms / self.count if self.count > 0 else 0.0

    @property
    def p50_ms(self) -> float:
        """Median latency."""
        return self._percentile(0.50)

    @property
    def p95_ms(self) -> float:
        """95th percentile latency."""
        return self._percentile(0.95)

    @property
    def p99_ms(self) -> float:
        """99th percentile latency."""
        return self._percentile(0.99)

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        return ((self.count - self.errors) / self.count * 100) if self.count > 0 else 100.0

    def _percentile(self, p: float) -> float:
        """Calculate percentile from samples."""
        if not self.durations_ms:
            return 0.0
        sorted_d = sorted(self.durations_ms)
        idx = int(len(sorted_d) * p)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def to_dict(self) -> dict[str, Any]:
        """Export as dictionary for Prometheus/Grafana."""
        return {
            "count": self.count,
            "errors": self.errors,
            "success_rate_pct": round(self.success_rate, 2),
            "avg_ms": round(self.avg_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
        }


# =============================================================================
# TELEMETRY: The observable system
# =============================================================================


class Telemetry:
    """Central observability for all core operations.

    Singleton pattern - one telemetry instance per process.

    Example:
        telemetry = Telemetry.get()

        # Track with context manager
        with telemetry.track("memory.save"):
            memory.save(content)

        # Track with decorator
        @telemetry.traced("memory.recall")
        def recall(query): ...

        # Get all metrics
        metrics = telemetry.get_metrics()
    """

    _instance: Telemetry | None = None

    def __init__(self) -> None:
        """Initialize telemetry. Use Telemetry.get() instead."""
        self._operations: dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._gauges: dict[str, float] = {}
        self._start_time = time.time()

    @classmethod
    def get(cls) -> Telemetry:
        """Get the singleton telemetry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset telemetry (useful for testing)."""
        cls._instance = None

    # -------------------------------------------------------------------------
    # TRACKING: How we measure
    # -------------------------------------------------------------------------

    @contextmanager
    def track(self, operation: str) -> Iterator[None]:
        """Track an operation with timing and error handling.

        Args:
            operation: Name like "vector_store.search" or "embedder.encode"

        Example:
            with telemetry.track("memory.save"):
                memory.save(content)
        """
        start = time.perf_counter()
        success = True

        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._operations[operation].record(duration_ms, success)

            logger.debug(f"{operation}: {duration_ms:.2f}ms {'✓' if success else '✗'}")

    def traced(self, operation: str) -> Callable:
        """Decorator to trace a function.

        Args:
            operation: Name for this operation

        Example:
            @telemetry.traced("embedder.encode")
            def encode(text):
                return model.encode(text)
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs):
                with self.track(operation):
                    return func(*args, **kwargs)

            return wrapper

        return decorator

    def record(self, operation: str, duration_ms: float, success: bool = True) -> None:
        """Manually record an operation (when context manager isn't suitable)."""
        self._operations[operation].record(duration_ms, success)

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge value (point-in-time measurement).

        Example:
            telemetry.gauge("vector_store.collection_size", 1000)
        """
        self._gauges[name] = value

    def increment(self, counter: str, amount: int = 1) -> None:
        """Increment a counter without timing."""
        # Use OperationMetrics but with 0 duration
        for _ in range(amount):
            self._operations[counter].record(0, success=True)

    # -------------------------------------------------------------------------
    # EXPORT: How we report
    # -------------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """Get all metrics for export.

        Returns dict suitable for Prometheus/Grafana/JSON export.
        """
        uptime_seconds = time.time() - self._start_time

        return {
            "uptime_seconds": round(uptime_seconds, 2),
            "operations": {name: metrics.to_dict() for name, metrics in self._operations.items()},
            "gauges": dict(self._gauges),
        }

    def get_operation(self, operation: str) -> OperationMetrics:
        """Get metrics for a specific operation."""
        return self._operations[operation]

    def summary(self) -> str:
        """Human-readable summary of all metrics."""
        lines = ["=" * 60, "TELEMETRY SUMMARY", "=" * 60]

        for name, metrics in sorted(self._operations.items()):
            if metrics.count > 0:
                lines.append(
                    f"{name:30} │ {metrics.count:>6} calls │ "
                    f"p50={metrics.p50_ms:>6.1f}ms │ p95={metrics.p95_ms:>6.1f}ms │ "
                    f"{metrics.success_rate:>5.1f}% ok"
                )

        lines.append("=" * 60)
        return "\n".join(lines)


# =============================================================================
# CONVENIENCE: Easy access
# =============================================================================


def get_telemetry() -> Telemetry:
    """Get the global telemetry instance."""
    return Telemetry.get()

# Observability

Every operation is tracked. Here's how to see what's happening.

---

## Quick Start

```python
from core import Telemetry

# Get the metrics
telemetry = Telemetry.get()
print(telemetry.summary())
```

Output:
```
============================================================
TELEMETRY SUMMARY
============================================================
memory.save                    │  20 calls │ p50=12.2ms │ 100.0% ok
memory.recall                  │  15 calls │ p50=10.7ms │ 100.0% ok
embedder.encode                │  35 calls │ p50= 6.1ms │ 100.0% ok
vector_store.search            │  15 calls │ p50= 4.5ms │ 100.0% ok
============================================================
```

---

## What's Tracked

### Per Operation

| Metric | Description |
|--------|-------------|
| `count` | How many times called |
| `errors` | How many failed |
| `success_rate` | Percentage that succeeded |
| `avg_ms` | Average latency |
| `p50_ms` | Median latency (50th percentile) |
| `p95_ms` | 95th percentile latency |
| `p99_ms` | 99th percentile latency |

### Operations Tracked

| Operation | Description |
|-----------|-------------|
| `memory.save` | Saving a memory |
| `memory.recall` | Searching memories |
| `memory.get_project_context` | Getting project context |
| `memory.get_stats` | Getting system stats |
| `memory.clear_project` | Deleting project memories |
| `embedder.encode` | Text → vector conversion |
| `embedder.encode_batch` | Batch encoding |
| `embedder.load_model` | Model initialization |
| `vector_store.save` | Saving to Qdrant |
| `vector_store.search` | Searching Qdrant |
| `vector_store.scroll` | Listing from Qdrant |
| `vector_store.delete` | Deleting from Qdrant |
| `vector_store.connect` | Connecting to Qdrant |

---

## Accessing Metrics

### Python API

```python
from core import Telemetry

telemetry = Telemetry.get()

# Full metrics (OTEL-compatible)
metrics = telemetry.get_metrics()
print(metrics)
# {
#   "uptime_seconds": 120.5,
#   "operations": {
#     "memory.save": {
#       "count": 20,
#       "errors": 0,
#       "success_rate_pct": 100.0,
#       "avg_ms": 13.3,
#       "p50_ms": 12.2,
#       "p95_ms": 37.9,
#       "p99_ms": 45.2
#     },
#     ...
#   },
#   "gauges": {
#     "vector_store.agent_memory.size": 1000
#   }
# }

# Specific operation
save_metrics = telemetry.get_operation("memory.save")
print(f"Saves: {save_metrics.count}, avg: {save_metrics.avg_ms}ms")

# Human-readable summary
print(telemetry.summary())
```

### CLI

```bash
# Get memory stats
python -m memory.cli stats

# Output:
# 📊 Memory System Stats
# ────────────────────────────────────
# Total memories:  150
# Memory files:    12
# Storage:         ~/.claude/memory
#
# By type:
#   note: 80
#   decision: 45
#   learning: 25
```

---

## Integration with Monitoring Systems

### Prometheus

The metrics format is designed to be easily converted:

```python
from core import Telemetry
from prometheus_client import Counter, Histogram

telemetry = Telemetry.get()
metrics = telemetry.get_metrics()

# Convert to Prometheus metrics
for name, data in metrics["operations"].items():
    # Create counter
    counter = Counter(f'{name.replace(".", "_")}_total', f'Total {name} calls')
    counter.inc(data["count"])

    # Create histogram
    histogram = Histogram(f'{name.replace(".", "_")}_duration_ms', f'{name} duration')
    histogram.observe(data["avg_ms"])
```

### Grafana Dashboard

Key panels to create:

1. **Request Rate**: `sum(rate(memory_save_total[5m]))`
2. **Error Rate**: `sum(rate(memory_errors_total[5m]))`
3. **Latency P95**: `histogram_quantile(0.95, memory_save_duration_ms)`
4. **Vector Store Size**: `vector_store_agent_memory_size`

### JSON Export

```python
import json
from core import Telemetry

metrics = Telemetry.get().get_metrics()
print(json.dumps(metrics, indent=2))
```

---

## Adding Custom Telemetry

### Track a Custom Operation

```python
from core import Telemetry

telemetry = Telemetry.get()

# Using context manager
with telemetry.track("my_custom_operation"):
    # ... your code ...
    pass

# Using decorator
@telemetry.traced("my_function")
def my_function():
    # ... your code ...
    pass

# Manual recording
import time
start = time.perf_counter()
# ... your code ...
duration_ms = (time.perf_counter() - start) * 1000
telemetry.record("manual_operation", duration_ms, success=True)
```

### Set a Gauge

```python
from core import Telemetry

telemetry = Telemetry.get()

# Point-in-time measurement
telemetry.gauge("queue_size", 42)
telemetry.gauge("cache_hit_rate", 0.85)
```

---

## Debugging Performance

### Find Slow Operations

```python
from core import Telemetry

telemetry = Telemetry.get()

for name, metrics in telemetry.get_metrics()["operations"].items():
    if metrics["p95_ms"] > 100:  # More than 100ms at p95
        print(f"SLOW: {name} - p95={metrics['p95_ms']}ms")
```

### Find Error-Prone Operations

```python
from core import Telemetry

telemetry = Telemetry.get()

for name, metrics in telemetry.get_metrics()["operations"].items():
    if metrics["success_rate_pct"] < 99:
        print(f"ERRORS: {name} - {metrics['errors']} failures")
```

---

## Best Practices

1. **Check metrics after major operations**
   ```python
   # After a batch import
   print(telemetry.summary())
   ```

2. **Set alerts on error rates**
   ```python
   if telemetry.get_operation("memory.save").success_rate < 99:
       alert("Memory save errors detected!")
   ```

3. **Monitor latency trends**
   ```python
   # If p95 is 5x higher than p50, investigate
   metrics = telemetry.get_operation("memory.recall")
   if metrics.p95_ms > metrics.p50_ms * 5:
       print("High latency variance detected")
   ```

4. **Reset for clean measurements**
   ```python
   # In tests
   Telemetry.reset()
   # ... run operation ...
   metrics = Telemetry.get().get_metrics()
   ```

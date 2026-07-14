"""docker-compose.yaml defaults must be safe for strangers.

No fixed container names (side-by-side instances), no prod data paths as
volume defaults (a second instance must never aim at live data), and every
published port bound to loopback.
"""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).parent.parent / "docker-compose.yaml"


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_no_container_names():
    offenders = [name for name, svc in _services().items() if "container_name" in svc]
    assert offenders == [], f"container_name pins these services: {offenders}"

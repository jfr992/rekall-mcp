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


def test_no_prod_data_paths_in_volume_defaults():
    offenders = []
    for name, svc in _services().items():
        for vol in svc.get("volumes", []):
            entry = vol if isinstance(vol, str) else str(vol.get("source", ""))
            if "~/.claude" in entry or "$HOME" in entry:
                offenders.append(f"{name}: {vol}")
    assert offenders == [], f"volume defaults point at prod data: {offenders}"


def test_published_ports_are_loopback_only():
    offenders = []
    for name, svc in _services().items():
        for port in svc.get("ports", []):
            if not str(port).startswith("127.0.0.1:"):
                offenders.append(f"{name}: {port}")
    assert offenders == [], f"ports published beyond loopback: {offenders}"

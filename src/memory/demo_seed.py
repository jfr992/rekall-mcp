"""Demo corpus for `rekall demo`: 20 realistic SWE memories, manifest-tracked.

Fictional projects only (demo-payments-api, demo-infra); every content string
is prefixed "[demo]" so seeded data is unmistakable inside any store. The
corpus carries exactly one same-type conflict pair (webhook retry limit 5 → 3,
shared "Stripe" entity) so freshness marks the older entry outdated on recall,
and exactly one open TODO. clean() deletes by manifest ids ONLY — it can never
touch memories it didn't seed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.manager import MemoryManager

MANIFEST_NAME = "manifest.json"

_PAY = "demo-payments-api"
_INFRA = "demo-infra"

# Order matters for the conflict pair: the 5-attempts entry is saved first so
# its timestamp is older and freshness stubs it out behind the 3-attempts entry.
DEMO_MEMORIES: list[dict[str, str]] = [
    {
        "content": "[demo] Chose PostgreSQL over DynamoDB for demo-payments-api — the ledger needs transactional joins.",
        "type": "decision",
        "project": _PAY,
    },
    {
        "content": "[demo] Settled on Stripe as the payment processor; Braintree lost on webhook ergonomics.",
        "type": "decision",
        "project": _PAY,
    },
    {
        "content": "[demo] Stripe webhook retry limit is 5 attempts before dead-lettering.",
        "type": "requirement",
        "project": _PAY,
    },
    {
        "content": "[demo] Stripe webhook retry limit is 3 attempts before dead-lettering.",
        "type": "requirement",
        "project": _PAY,
    },
    {
        "content": "[demo] Stripe idempotency keys expire after 24 hours — replaying an old key silently creates a duplicate charge.",
        "type": "learning",
        "project": _PAY,
    },
    {
        "content": "[demo] demo-payments-api exposes /api/v1/charges and /api/v1/refunds; both require the X-Request-Id header.",
        "type": "fact",
        "project": _PAY,
    },
    {
        "content": "[demo] Team prefers FastAPI dependency injection over module-level singletons in demo-payments-api.",
        "type": "preference",
        "project": _PAY,
    },
    {
        "content": "[demo] Two concurrent captures raced on one authorization — fixed with SELECT FOR UPDATE on the payment row.",
        "type": "learning",
        "project": _PAY,
    },
    {
        "content": "[demo] Refund settlement to the ledger runs nightly at 02:00 UTC via the reconcile-worker cron.",
        "type": "fact",
        "project": _PAY,
    },
    {
        "content": "[demo] Currency amounts are stored as integer minor units (cents), never floats, across demo-payments-api.",
        "type": "decision",
        "project": _PAY,
    },
    {
        "content": "[demo] PCI scope: raw card numbers never touch demo-payments-api; only Stripe tokens are stored.",
        "type": "requirement",
        "project": _PAY,
    },
    {
        "content": "[demo] Standardized demo-infra on Terraform 1.7 with remote state in S3 plus DynamoDB locking.",
        "type": "decision",
        "project": _INFRA,
    },
    {
        "content": "[demo] Karpenter over-provisioned spot nodes with consolidation left at WhenUnderutilized — switched to WhenEmpty.",
        "type": "learning",
        "project": _INFRA,
    },
    {
        "content": "[demo] The staging cluster for demo-infra runs Kubernetes 1.29 on EKS in us-east-1.",
        "type": "fact",
        "project": _INFRA,
    },
    {
        "content": "[demo] Prefer kustomize overlays over Helm charts for demo-infra internal services.",
        "type": "preference",
        "project": _INFRA,
    },
    {
        "content": "[demo] Every demo-infra service must ship a /healthz endpoint before it gets a load balancer target group.",
        "type": "requirement",
        "project": _INFRA,
    },
    {
        "content": "[demo] Grafana dashboards broke after the Prometheus 2.50 upgrade — the le label became a float; pinned the bucket queries.",
        "type": "learning",
        "project": _INFRA,
    },
    {
        "content": "[demo] TODO: rotate the Grafana admin token for demo-infra staging before the next security audit.",
        "type": "note",
        "project": _INFRA,
    },
    {
        "content": "[demo] Alert routing goes through PagerDuty, not Slack — Slack alerts kept getting muted on weekends.",
        "type": "decision",
        "project": _INFRA,
    },
    {
        "content": "[demo] demo-infra CI runs on GitHub Actions with a self-hosted runner pool labeled infra-large.",
        "type": "fact",
        "project": _INFRA,
    },
]

SUGGESTED_QUERIES: list[str] = [
    "What is the Stripe webhook retry limit?",
    "Which database did we pick for the payments API?",
    "What is still TODO in demo-infra?",
]


def seed(manager: MemoryManager, demo_dir: Path | None = None) -> list[str]:
    """Save the demo corpus and record the exact ids in <demo_dir>/manifest.json.

    The manifest is rewritten after every save — a crash mid-seed leaves it
    covering every id already in the store, so --clean can still remove them.
    """
    demo_dir = Path(demo_dir) if demo_dir is not None else manager.memory_dir.parent
    demo_dir.mkdir(parents=True, exist_ok=True)
    manifest = demo_dir / MANIFEST_NAME
    ids: list[str] = []
    for entry in DEMO_MEMORIES:
        ids.append(manager.save(entry["content"], type=entry["type"], project=entry["project"]))
        manifest.write_text(json.dumps({"memory_ids": ids}, indent=2))
    return ids


def clean(manager: MemoryManager, manifest_path: Path) -> tuple[int, list[str]]:
    """Delete exactly the manifest's ids; anything else in the store survives.

    Ids whose deletion raised stay in the manifest so a re-run can retry them;
    the manifest is removed only when nothing failed. Returns (deleted, failed).
    """
    manifest_path = Path(manifest_path)
    ids = json.loads(manifest_path.read_text())["memory_ids"]
    deleted = 0
    failed: list[str] = []
    for memory_id in ids:
        try:
            if manager.delete(memory_id):
                deleted += 1
        except Exception:
            failed.append(memory_id)
    if failed:
        manifest_path.write_text(json.dumps({"memory_ids": failed}, indent=2))
    else:
        manifest_path.unlink()
    return deleted, failed

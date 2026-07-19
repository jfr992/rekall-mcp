"""Named lock around read-reclassify-write on a memory's payload (Codex F11:
concurrent update_payload calls race without one).
"""

import threading
import time

from memory.reinforce import reinforce_lock


def test_reinforce_lock_is_reentrant_free_and_releases(tmp_path):
    lock_path = tmp_path / "_reinforce.lock"

    with reinforce_lock(lock_path):
        pass

    # Lock file exists and a second acquisition after release succeeds.
    with reinforce_lock(lock_path):
        pass


def test_reinforce_lock_serializes_concurrent_critical_sections(tmp_path):
    lock_path = tmp_path / "_reinforce.lock"
    counter = {"value": 0}
    violations = []

    def critical_section():
        with reinforce_lock(lock_path):
            counter["value"] += 1
            local = counter["value"]
            time.sleep(0.02)
            if counter["value"] != local:
                violations.append(True)
            counter["value"] -= 1

    threads = [threading.Thread(target=critical_section) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert violations == []

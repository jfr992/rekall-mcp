# Classify job report

Status: DONE. Commits: 6beffb4 (server, compile, docs), plus the UI commit on top (see git log).

- Fix 1: ui/lib/api/client.ts reads the error body once via text(), then JSON.parse with raw-text fallback.
- Fix 2: compile.py gains ModelUnreachable, worthy_from_cache, breaker + progress kwargs. server.py POST starts a daemon-thread job (_WIKI_CLASSIFY_JOBS); GET returns status plus cache-only candidates. README/MIGRATION updated (one GET, POST row, required by test_docs_parity).
- Fix 3: useWikiCandidates(project) is a query (2s poll while running); useClassifyCandidates mutation; button "Classify" / "Classifying d/t...".

Deviations/concerns:
- GET reports "unconfigured" when idle and no model config (builds the llm closure, no model call).
- Job total is set from the scroll size up front so POST-while-running shows a real total.
- The three new component tests were written alongside the implementation (RED not observed separately); client and Python tests were observed RED.
- Jobs are in-memory, so a server restart leaves status idle (cache still serves candidates).

## Fix report

1. WikiStore.merge_cache (read+update+atomic write under the store lock); the job persists only its own new/changed entries through it. Test: either order keeps both; job never calls write_cache.
2. classify_candidates takes `flush` / `flush_every=10`; the job flushes every 10 memories and in `finally`. Test: worker dying after 12 memories leaves >=10 verdicts on disk.
3. Initial read_cache is inside the worker's try; failure yields status error (tested).
4. GET builds from `dict(job)` snapshot.
5. `candidatesRefetchInterval(status)` exported and tested (ui/tests/use-wiki-poll.test.ts).

RED observed for 1-3 and 5 (src stashed / fn missing). Item 4 has no dedicated test (snapshot refactor).
Note: the crash test raises KeyboardInterrupt in the worker thread, which pytest reports as one unhandled-thread-exception warning.

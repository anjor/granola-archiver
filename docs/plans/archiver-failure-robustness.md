# Plan: Archiver Failure Robustness

## Background

In June 2026 the archiver silently stopped committing notes for ~5 days. Two
independent faults combined, and the architecture turned a recoverable error
into permanent data loss:

1. A stale `.git/index.lock` in the notes repo made every `git commit` fail.
2. Each failed document was then **lost**, not retried, because of how the
   fetch watermark advances (see Problem 1 below).
3. Nobody noticed, because failing runs produce no alert (Problem 3).

A second, unrelated fault (`granola-client` pinned to a version Granola's API
now rejects) is fixed separately in PR #9. This plan covers the *robustness*
gaps that let a transient git error become 5 days of missing notes.

## Problem 1 — The watermark advances past failed documents (data loss)

`run_archiver()` in `archiver/main.py`:

- Fetches documents with `updated_at > fetch_since`, where
  `fetch_since = state_tracker.get_last_run_timestamp()`.
- `get_last_run_timestamp()` returns the most recent `archive_runs.run_at`.
- `update_last_run()` inserts a row with `run_at = now()` on **every** run,
  whether or not documents failed.

Failed documents are not written to `archived_documents` (so `is_archived()`
would correctly re-process them) — but the watermark has already moved to
`now()`, so on the next run they're below the window and never fetched again.

**The watermark conflates "wall-clock time of last run" with "high-water mark
of document state we have durably processed." Those are not the same thing.**

### Fix: explicit retry queue, decoupled from the watermark

Add a `pending_documents` table (or reuse a `status` column) tracking documents
that were fetched but not successfully archived:

```
pending_documents(
    document_id TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL,   -- the updated_at we tried to archive
    first_failed_at TEXT NOT NULL,
    last_error  TEXT,
    attempts    INTEGER DEFAULT 1
)
```

Run loop becomes:

1. Fetch `documents_since(watermark)` **plus** re-fetch every id in
   `pending_documents`.
2. Attempt to archive each. On success → `mark_archived()` + delete from
   `pending_documents`. On failure → upsert into `pending_documents`
   (increment `attempts`, record error).
3. Advance the watermark to `now()` only as before — but now failures are no
   longer lost, because the retry queue is independent of the watermark.

This also handles transient API/network/git errors generically, not just this
one incident.

Alternative considered (rejected): cap the watermark advance at
`min(updated_at)` of failed docs. Correct, but fiddly around tz handling and
edge cases, and it stalls *all* progress behind one poison document. The retry
queue isolates failures per-document.

## Problem 2 — No stale-lock detection in git operations

`git_manager.write_and_commit()` fails hard when `.git/index.lock` exists.
A lock left by an interrupted process never clears on its own.

### Fix: detect-and-recover with guards

On a commit failure caused by `index.lock`:

- Check the lock's age and whether any process holds it (no live git process,
  age greater than the polling interval → almost certainly stale).
- If clearly stale: remove it and retry the commit **once**, logging loudly.
- If not clearly stale (recent, or a git process is running): fail without
  deleting, and surface via the alert in Problem 3.

Keep auto-removal conservative — only when stale beyond doubt — so we never
race a legitimate concurrent git operation.

## Problem 3 — Silent failure (no alerting)

The process exits non-zero on failure (`sys.exit(1)`), but launchd discards it.
Five days passed before a human noticed.

### Fix: alert on repeated failure

- Track consecutive failed runs in state (or derive from `archive_runs`).
- After N consecutive failures (e.g. 3), emit a macOS notification via
  `osascript -e 'display notification ...'` and/or write a sentinel file the
  user can spot.
- Optionally include the run's exit reason.

Cheap, local, no new dependencies. The goal is simply: a sustained failure
becomes visible the same day, not the same week.

## Minor cleanups

- Fix the misleading docstring on `get_last_run_timestamp()` — it says "last
  successful run" but returns the last run of any kind. That wording is
  arguably what masked this bug in review.

## Suggested sequencing

1. Problem 1 (retry queue) — highest value; prevents data loss. TDD: write a
   test that fails a commit, asserts the doc is retried and archived next run.
2. Problem 3 (alerting) — cheap; makes future regressions visible.
3. Problem 2 (stale-lock recovery) — nice-to-have once 1 + 3 exist, since the
   retry queue + alert already prevent silent data loss from a stale lock.

## Out of scope

- The `granola-client` version fix (PR #9).
- Reworking the launchd scheduling / log paths (note: there's also a stray
  literal `~/.local/...` log directory inside the repo worth cleaning up
  separately).

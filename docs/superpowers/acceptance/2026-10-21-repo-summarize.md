# Acceptance: repo-summarize self-run (real agy)

Run 1 result: **FAILED, exit 3 (aborted), nothing published.** Fixed by Task 13a (tool-denied re-ask). Run 2 (below): **PASSED** after three discovery/plan fixes.

## Environment
- Date: 2026-10-21 09:24 PDT (run started ~09:20)
- Commit: e9cf1660cefa067379ad499e759a1948cedd61b4
- agy version: 1.4.4
- Sandbox kind: not printed by the tool; not recorded
- Probe result: `probe-no-access-observed` (docs/.repo-summarize/probe.json)

## Estimate (`--estimate .`)
```
catalog       2  ~114 KB of prompts
plan          1
chapters      3
index         1
total         7  upper bound before cache hits and re-asks
```

## Real run (`time bin/repo-summarize --max-calls 30 .`)
- Exit code: 3
- Error: `repo-summarize: aborted: 3 consecutive backend failures; nothing published`
- Wall time: 3:19.39 total
- provenance.json: not written (run aborted). Stats below come from `runs/20261021T162037Zf470/log.jsonl`.

| stage | key | bytes_in | bytes_out | ok | reason |
|---|---|---|---|---|---|
| catalog | f3c5ffe2e66f | 60149 | 2761 | yes | |
| catalog | f4df003cd7ce | 53404 | 2218 | yes | |
| plan | ce9d74e31375 | 6326 | 0 | no | tool-denied |
| plan | 5d2bbf68ad98 | 6381 | 0 | no | tool-denied |
| chapter | a46a2336157e | 15762 | 4244 | yes | |
| chapter | b83850002eee | 3414 | 0 | no | tool-denied |
| chapter | 0b484a9493e1 | 3469 | 0 | no | tool-denied |
| chapter | 975bae804eec | 3343 | 0 | no | tool-denied |

- Calls: 8 (catalog 2, plan 2, chapter 4), 0 cache hits, 3 successes cached.
- Observation: all 5 failures are `tool-denied` (empty reply). The first chapter call succeeded, so the failures are intermittent or content-dependent; the plan stage failed twice (the plan stage may have been retried once, the chapter stage then hit the breaker at 3 consecutive failures).
- Coverage counts, label distribution, chapter list: not available (no book published; `docs/architecture/` was not created).

## Step 4 (re-run checks)
Not run: there is no published book to re-run against. No test edits were made, so nothing to revert.

## Own read of book quality
Nothing to judge: no book was produced. Only signal: catalog stage works against real agy (2/2); plan and later chapter calls return `tool-denied`.

## Run 2 (2026-10-21 14:52–15:23 PDT, agy 1.4.4, sandbox-exec)

Every run ran with `env -u REPO_SUMMARIZE_CMD`: the user's `~/.zprofile` exports the v1 value `agyy -p`, a wrapper under `~/Github`. The sandbox denies that path, so every call exited 126 (2a).

| # | Commit | Exit | Calls (cache hits) | Wall | Finding → fix |
|---|---|---|---|---|---|
| 2a | 08c5c4e | 3 | 3 (0) | 0:00.4 | exit 126 ×3, opaque abort → `ecc5ec6` readable reason + README note |
| 2b | ecc5ec6 | 0 | 8 (0) | 4:56 | book narrated the README only: `bin/repo-summarize` skipped (shebang `uv` unknown, 105 KB > 100 KB limit) → `a9759ad` |
| 2c | a9759ad | 0 | 7 (1) | 4:02 | main flow now on `bin/repo-summarize`; INDEX titled `book-mode` → `4479320`; stale run-2b plan reused (extensionless dirs invisible to `top_dirs`) → `8d9eebb` |
| 2d | 4479320 | 0 | 6 (2) | 4:37 | cache: unchanged catalog batches hit |
| 2e | 8d9eebb | 0 | 7 (2) | 3:42 | plan replaced and saved (`top_dirs: [bin]`) |
| 2f | 8d9eebb | 0 | 0 (7) | — | step-4 no-change re-run: zero calls |

Run 2e: tool-denied 0; plan `model`; no stub chapters; chapters Orientation and Project Overview / Documentation Generation Pipeline / Testing and Contribution Guidelines; coverage discovered 31, included 19, catalogued 19; skipped generated-docs 7, unsupported-type 5 (`docs/superpowers/*.md` by design §6.1).

Cited claims checked against source: `discover` :132, `run_catalog` :816, `run_plan` :1059 — all start at the named function.

Own read: the main flow is a correct stage-by-stage walk of the real code with real excerpts. Weakness: a 105 KB file only fits as signature lines, so the model guesses end lines; every main-flow step is labelled `not-shown` and some excerpts run past the function (v2.1: clip excerpts at the next top-level definition, or show full bodies of the functions a step names). Against the answer keys: Q1 partial (pytest + stub, no exact command), Q2 yes (budget constants quoted), Q3 partial (timeout setting, no breaker/exit 3).

## Human review — pending
Step 3 is for the user. Do not score from this doc until a book exists.

Questions and answer keys (written before reading any book):
1. "How do I run the tests?" Key: `uv run --with pytest pytest -q`.
2. "Where would I change the chapter budget?" Key: the `fill_budget` / budget constants in `bin/repo-summarize`.
3. "What happens if the backend times out?" Key: `CallFailed("timeout")`, the circuit breaker, exit 3.

| Task | Correct answer | Correct source location | Time taken | Notes |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

Confidently wrong recommendations (count): 

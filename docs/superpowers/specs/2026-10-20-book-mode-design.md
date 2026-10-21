# repo-summarize v2: Book Mode — Design

**Date**: 2026-10-20
**Status**: Draft, awaiting review
**Spike evidence**: run on `ne1cc/lakehouse-engine` (158 tracked files), summarized in §11

## 1. Goal

Run `repo-summarize` once (it can run in the background) on an unfamiliar repo, and get a short, ordered set of Markdown files a developer reads like a book to learn **how to develop in and contribute to** that repo.

**Success test**: after reading, a newcomer can (a) run and test the project, (b) find where to make a given change, (c) see what that change affects, and (d) check every important claim against the source in one click.

**Style**: terse, no filler. Diagrams are Mermaid. Every code excerpt is real source pasted by the script, never retyped by the model.

## 2. Non-goals (v2)

- Tree-sitter, symbol resolution, or typed call-graph edges (`calls`, `reads_from`, …). Edges stay heuristic imports, labelled honestly as imports.
- Q&A or chat over the repo, a rendered website, search.
- Parallel AI calls.
- Changing the default backend's billing model; quota protection is handled by caps (§8).

## 3. Output

```
docs/architecture/
  INDEX.md            start here: what the repo is, one system diagram, reading order
  01-<slug>.md …      6–12 chapters, read in order
  FILES.md            every file: purpose, key symbols, chapter, tests, imported-by
  reference/<path>.md only with --reference (per-file annotated walkthroughs, today's output)
  UNCERTAINTIES.md    what could not be verified: dropped refs, flagged citations, uncovered files,
                      DeepWiki claims not supported locally (§5.6)
  provenance.json     commit, dirty flag, generated_at, backend, prompt versions, DeepWiki use (§5.6)
  .repo-map.md  .repo-edges.tsv  .cache/  .progress.json  .repo-summarize.log
```

- Every generated file starts with `<!-- repo-summarize:v3 commit=<sha> -->`. The commit SHA (or `uncommitted`) records what source the doc describes.
- **Breaking change**: per-file docs move from `docs/architecture/<path>.md` to `docs/architecture/reference/<path>.md`. Old v2-marker docs are pruned as orphans (§7.4).

### Chapter format (fixed headings)

```
# NN. Title
> why read this now (from the plan)
## What this is           2–4 sentences
## How it fits together   one Mermaid diagram of the real flow
## How it works           numbered steps in execution order, ≤8 pasted excerpts
## Where to change things "To <task>: `path:line` → `function`" (4–6 bullets)
## Gotchas                3–6 bullets, each with `path:line`
Files in this chapter / Tests          ← script-generated footer
```

Chapter 01 is always **Orientation** (what it is, stack, layout, how to install, run, test, build). Chapter 02 is always **The main flow**: one end-to-end path (an input becoming an output) across files, with every step backed by a pasted local excerpt. The last chapter is always **Contributing** (CI gates, conventions, PR flow).

### INDEX.md

The model writes a one-paragraph overview, a system Mermaid diagram, and one line per chapter on why it comes at that point. The script appends the chapter table (number, linked title, why) and a link to `FILES.md`. The model never writes link targets.

### FILES.md (deterministic, no model prose besides catalog purposes)

Grouped by top-level directory: `File | Purpose | Key symbols | Chapter | Tests | Imported by`. A trailing section, **"Not covered by a chapter"**, lists every catalogued file that no chapter contains, so nothing disappears silently.

## 4. Pipeline

| # | Stage | AI calls | Input → Output |
|---|---|---|---|
| 0 | Scan | 0 | files, import edges, entry points, manifest commands → `.repo-map.md`, `.repo-edges.tsv` |
| 0b | DeepWiki research (opt-in, §5.6) | 0 (HTTP only) | repo name → topic tree, page slices, 3 answers (external, unverified) |
| 1 | Catalog | ⌈source bytes / 60 KB⌉ | batched file contents → one row per file: `path⇥purpose⇥symbols` |
| 2 | Plan | 1 | README head + edges + catalog → `NN⇥slug⇥title⇥why⇥files` |
| 3 | Attach | 0 | deterministic placement fixes (§6.2) |
| 4 | Chapters | 1 per chapter | chapter source (line-numbered) + catalog + tests → chapter Markdown with `[[ref:path:A-B]]` |
| 5 | Resolve | 0 | paste refs, verify citations (§6.3) |
| 6 | Index | 1 | chapter titles + "What this is" sections + top-level edges → INDEX.md |
| 7 | FILES.md | 0 | catalog + plan + edges |
| R | Reference (opt-in) | 1 per file | today's per-file pass, written to `reference/` |

Typical cost: about 20 calls for a 150-file repo (lakehouse-engine: 8 catalog + 1 plan + 10 chapters + 1 index). Today's tool needs about 124 calls on the same repo.

Every model stage follows **validate → retry once, listing the violations → accept with warnings**. Warnings are written to the log and to a "Known gaps" line in the affected doc.

## 5. Stage details

### 5.0 Scan (no AI)

**Discovery** (fixes old flaws F1, F2):
- In a git repo: `git ls-files -co --exclude-standard`. Otherwise `find`. The `fd` branch is removed, so there is one discovery path.
- Included: known code extensions, plus `yml yaml toml json sql properties ini cfg`, plus `Dockerfile*`, `Makefile`, `justfile`, `*.md` at the repo root and under `.github/`, plus extensionless files whose first line is a shebang (`bash|sh|zsh|python|node|ruby|perl`).
- Excluded: lockfiles, minified files, sourcemaps, binary files (`LC_ALL=C grep -Iq .` fails), files over 100 KB (listed as skipped in FILES.md), `docs/architecture/**`, and the secret files in §9.

**Import edges** (fixes F3):
- The existing extractors for py, js/ts, lua, sh and c/c++, plus Go (`import "x"` → files in the suffix-matching package dir), Rust (`mod x;`, `use crate::a::b`), and Java/Kotlin (`import a.b.C` → `a/b/C.(java|kt)`).
- **Re-export shims**: if an imported file is at least 80% import lines, edges pass through it one hop. The spike missed `tests/test_contracts_ingestion.py` because it imports through such a shim.
- The repo map header lists discovered languages that have no extractor (for example Swift and SQL).

**Entry points**: name heuristics (`main|app|index|server|cli|__main__`), plus targets named in `[project.scripts]`, the `package.json` `bin`/`scripts`, and the Dockerfile `CMD`/`ENTRYPOINT`.

**Manifest commands** (fed to Orientation and Contributing, no AI): Makefile targets, `package.json` scripts, `pyproject` scripts, justfile recipes, and `run:` steps from `.github/workflows/*.yml`.

### 5.1 Catalog

- Batches of ≤ 60 KB of source. Each file is capped at 400 lines in the prompt, with a truncation note.
- Output contract: exactly one tab-separated row per input file, in order. Purpose is one sentence of at most 18 words, about the file's *role*. Key symbols: up to 5, or `-`.
- Validation: each input path appears exactly once, and no invented paths. Missing rows are retried once in a batch of their own. A file still missing gets the purpose `(catalog failed)`.
- Cached per file (§7). Only changed files are re-catalogued, batched together.

### 5.2 Plan

- The prompt gives the constraints: 6–12 chapters (scaled to file count), 01 = Orientation, last = Contributing, entry points within the first two chapters, each file in at most one chapter.
- Large repos: if the catalog exceeds 80 KB, the planner gets per-directory lines (directory, file count, its top 5 files by fan-in with their purposes) instead of every row.
- Validation: real paths only, no duplicates, chapter count in range, entry points placed in chapters 01–02, sum of chapter source ≤ 100 KB each (the catalog shows bytes per file so the planner can balance).
- The cache key is the **structure** (sorted paths and edges), not the catalog prose. Editing code inside files doesn't trigger a re-plan. `--replan` forces one.

### 5.3 Attach (no AI)

1. Entry points still placed after chapter 02 move into 02.
2. Tests attach to the chapter of the file they import (edges, through shims).
3. Unplaced non-code files (`*.yml`, `*.properties`, `Dockerfile`, compose files) attach to the chapter that owns most code files in the same or parent directory. If there is none, root-level build, CI and Docker files go to 01, and `.github/**` goes to the last chapter.
4. Anything left goes to FILES.md "Not covered by a chapter".

### 5.4 Chapters

- Prompt: chapter metadata (number, title, why, previous/next titles), the fixed headings and rules from §3, catalog paths and purposes for context, the chapter's tests, manifest commands (01 and last only), and the chapter source with line numbers.
- Budget: 100 KB. If over, files are shown in full in fan-in order; the rest get the first 60 lines plus their key symbols, and the chapter's "Known gaps" line names them.
- The model may write at most 8 `[[ref:path:A-B]]` lines, each 5–30 lines long. It never writes code blocks of repository source.

### 5.5 Index

One call. Prompt: chapter list, each chapter's "What this is" section, top-level directory edges, README head. Validated for headings and Mermaid; links are added by the script.

### 5.6 DeepWiki research (optional, `--deepwiki`)

**Role**: DeepWiki *suggests* topics, flows and file relationships. The local checkout is the only source of truth, and nothing reaches a chapter without a local citation that passes §6.3. DeepWiki never replaces the catalog, the per-file docs, or the planner.

**Transport**: the script speaks MCP itself, using `curl` + `jq` JSON-RPC `tools/call` against `https://mcp.deepwiki.com/mcp` (Streamable HTTP, replies arrive as SSE `data:` lines). The `agy` backend gets no tools and no MCP access. `REPO_SUMMARIZE_DEEPWIKI_URL` overrides the endpoint; tests point it at a stub.

**Eligibility.** Every check must pass, or the step is skipped with a logged reason:
1. The `--deepwiki` flag is given. It is off by default: the repo name leaves the machine.
2. `origin` is a `github.com` remote. Credentials embedded in the remote URL are stripped and never written anywhere.
3. The repo is publicly reachable: an unauthenticated `GET https://api.github.com/repos/<o>/<r>` returns 200. A private repo's name is never sent.
4. DeepWiki has the repo indexed. The "Repository not found" reply means skip, with a pointer to `deepwiki.com/<o>/<r>` for indexing.

**What is sent**: the repo name and three fixed questions only. Never source, catalog text, secrets, env values, or uncommitted changes.

**Calls** (once per run, cached by retrieval date; no `agy` quota used):
1. `read_wiki_structure` → topic tree (about 2 KB), passed to the planner as "external topic hints (unverified)".
2. `read_wiki_contents` → split into pages on its page headings. Each chapter prompt gets at most 15 KB of the 1–2 best-matching pages, matched by file paths shared between the page's `Sources:` lines and the chapter's files. Labelled "external notes, may describe a different commit; verify against the source below, cite only local lines."
3. `ask_wiki_question` × 3 (the real tool name; it was `ask_question` in the request). The questions:
   - What are the main components and entry points?
   - Describe one representative end-to-end flow, and which files implement each step.
   - How do developers run, test, and debug it locally?

   Answers go to the planner (topics, the main flow for chapter 02) and to chapter 01.

**Local verification** (no AI). Each DeepWiki claim gets one label: `verified` / `external-only` / `inferred` / `conflicting`.
- **Cited sources** `path:A-B`: the path exists locally and the range is in bounds → `verified`. The path is missing or out of range → `conflicting`, which usually means DeepWiki indexed an older commit.
- **Flow answer**: for each consecutive file pair, an import-edge path of length ≤ 2 exists → `verified`. A path exists but is longer → `inferred`. No path → `external-only`.
- **Chapter 02 must include ≥ 1 flow** where every step has a resolved local ref. If the DeepWiki flow cannot be verified, chapter 02 falls back to the flow from the local entry point.

Labels are recorded in UNCERTAINTIES.md. Only `verified` relationships appear in chapters.

**Failure**: any HTTP error, timeout (60 s per call) or malformed reply → log it, set `deepwiki.used=false` with the reason, and continue fully local. DeepWiki never fails a run.

### 5.7 UNCERTAINTIES.md and provenance.json (no AI)

- **UNCERTAINTIES.md** is generated from run state:
  - per chapter: dropped refs, flagged or corrected citations, "partially shown" files;
  - files not covered by any chapter;
  - catalog failures;
  - DeepWiki claims labelled `external-only`, `inferred` or `conflicting`, each with what was checked.
- **provenance.json**: `{ commit, dirty, branch, generated_at (ISO 8601 with offset), backend_cmd (no secrets), prompt_versions, calls_by_stage, deepwiki: { used, skipped_reason, retrieved_at, pages_used, questions } }`. `retrieved_at` is when DeepWiki was queried. It is never presented as the commit DeepWiki describes.

## 6. Verification (the trust layer)

### 6.1 Structure
- Required headings are present.
- Mermaid passes through the existing `wrap_mermaid` and the keyword-ID rule.

### 6.2 Placement
Covered by §5.2 validation and §5.3 attach.

### 6.3 Citations (spike found 1–9 line drift and one wrong function pointer)
- **Refs**: path exists, `1 ≤ A ≤ B ≤ EOF`, length ≤ 40 lines. **Snap**: if a `def|class|function|func|fn|CREATE` line lies ≤ 15 lines above `A` inside the same block, extend `A` up to it. Invalid refs are dropped and listed under "Known gaps". Pasted lines go through the secret redactor (§9).
- **Inline `path:N` citations** (Gotchas, Where to change things): the claim's backticked identifiers must appear within ±5 lines of `N`. If they're found nearby, rewrite `N` to the exact line. If not found in the file at all, the bullet is flagged with ⚠ and logged.
- **"Where to change things"**: the named function must exist in the cited file (`grep` for its definition). If it doesn't, the bullet is flagged.

### 6.4 Reported metrics
Every run prints and logs: catalog missing/invented, plan violations before and after retry, refs pasted/snapped/dropped, citations exact/corrected/flagged, and files not covered.

## 7. Caching and incremental runs

`docs/architecture/.cache/manifest.tsv` stores `key⇥hash` rows. Hashes use `shasum -a 256`, falling back to `sha256sum`.

| Unit | Fingerprint |
|---|---|
| Catalog row | file content + catalog prompt version |
| Plan | sorted paths + edges + plan prompt version |
| Chapter | its files' content + tests list + plan row + manifest commands (01/last) + chapter prompt version + backend command |
| Index | chapter titles + "What this is" sections + index prompt version |
| Reference doc | file content + supplied dependency context + reference prompt version |

### Pruning (§7.4)
After a full run, delete marker-bearing docs that no longer correspond to a file or chapter. Files without the marker are never touched.

## 8. Run control and quota

- `--estimate`: runs Scan and prints calls per stage and approximate prompt KB. Chapter calls before planning are estimated as clamp(files ÷ 12, 6, 12). No AI calls, no writes.
- `--max-calls N`: stop cleanly with progress status `capped`, exit 4. A re-run resumes from the cache.
- `REPO_SUMMARIZE_TIMEOUT` (default 300 s): a bash 3.2 watchdog kills a hung call, which counts as a failure.
- Circuit breaker: 3 consecutive failures → status `aborted`, exit 3, with a "quota or backend problem?" hint.
- `--dry-run`: Scan only, written to a temp directory; prints the file list and paths. It writes nothing into the repo (fixes F5).
- Lock: `mkdir docs/architecture/.lock`, released on exit. A second run exits with an error.
- `.progress.json` carries `stage`, `done`, `total`, and the current item; filenames are JSON-escaped.

## 9. Safety

- **Backend contract**: the AI command must be a non-interactive, read-only text responder. The default stays `agy -p`. If the command contains `--dangerously-skip-permissions` or `--yolo`, the script prints a one-line warning: repository content is untrusted and becomes the prompt. The spike observed `agy` trying to run a shell command when given too little context, which non-yolo mode blocked.
- An empty reply whose stderr mentions a denied permission or tool counts as a failure, with that reason logged.
- **Secret exclusion**:
  - Never read: `.env` and `.env.*` (except `.example`, `.sample`, `.template`), `*.pem`, `*.key`, `*.p12`, `*id_rsa*`, `*credentials*.json`, `secrets/**`.
  - Redact before prompting and before pasting refs: `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{36,}`, `sk-[A-Za-z0-9_-]{20,}`, `xox[abpr]-[A-Za-z0-9-]+`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`, and `(password|secret|token|api_?key)\s*[:=]\s*['"]?[^\s'"]{8,}` with the value replaced by `[REDACTED]`.
  - Redaction counts go to the log.

## 10. CLI

```
repo-summarize [path]          book mode (default)
  --reference                  also write per-file walkthroughs to reference/
  --filter <substr>            reference mode only: restrict per-file docs
  --max-files N                reference mode only
  --estimate | --dry-run | --status | --open
  --force                      ignore cache      --replan   re-plan only
  --max-calls N
  --deepwiki                   optional external research for public, DeepWiki-indexed repos (§5.6)
env: REPO_SUMMARIZE_CMD (default "agy -p"), REPO_SUMMARIZE_TIMEOUT (default 300),
     REPO_SUMMARIZE_DEEPWIKI_URL (default https://mcp.deepwiki.com/mcp)
```

- Option values are validated: a missing or non-integer value gives a message and exit 2 (fixes F6).
- `--filter` and `--max-files` without `--reference` are an error, so a partial run can never overwrite the book (replaces F8).
- Reference mode keeps today's line and block prompts, adds the verbatim check (strip annotation lines, `diff` against the source, retry once, else fail the file), and uses the content-hash cache.

## 11. Spike evidence (lakehouse-engine, 2026-10-20, `agy -p`)

- Catalog: 8 calls, 124 files, 0 missing, 0 invented; purposes described each file's role. It spotted that the `olist_lakehouse` package is compatibility shims.
- Plan: 1 call, 10 chapters in a sensible arc, 0 bad paths, 0 duplicates. Defects: the CLI entry point was in chapter 9; dbt schema `.yml`, Trino/MinIO deploy config and Dockerfiles were unplaced; tests were unlinked. §5.3 addresses these.
- Chapter 3: 1 call, about 20 s, 524 words of prose, 8 refs all valid, Mermaid named after real functions, useful "Where to change things". Defects: inline line numbers drifted 1–9 lines; one task pointed at the wrong function; one excerpt started mid-function; one test was missed through a shim. §6.3 and §5.0 address these.

## 12. Testing

- `tests/run.sh` runs `tests/cases/*.sh`. The existing smoke test becomes the reference-mode case.
- The **stage-aware stub backend** recognizes each stage's prompt header and returns canned replies, including deliberate faults: a missing catalog row, an invented path, a misplaced entry point, an out-of-range ref, a citation off by 3 lines, a citation of a nonexistent function, and a tool-permission denial.
- Fixture repo `tests/fixtures/mini/`: py package with a shim, a test, a YAML config, a Dockerfile, a Makefile, an extensionless bash script, `src/build/x.py`, a `.env` file and a planted fake token.
- Assertions:
  - Each fault is caught and handled as §6 specifies.
  - The `.env` content and the token never appear in any prompt or doc.
  - Dry-run leaves `git status` clean.
  - Cache: touch → no calls; edit a file → only its catalog row plus its chapter regenerate.
  - `--max-calls` stops and resumes.
  - DeepWiki, against a stub at `REPO_SUMMARIZE_DEEPWIKI_URL`:
    - each source citation gets the right label (`verified` / `conflicting`);
    - a flow with an unreachable file pair gets `external-only`, and chapter 02 falls back to the local flow;
    - "Repository not found", an HTTP 500 and a private repo all skip with a reason, and the run still succeeds;
    - the request bodies contain only the repo name and the fixed questions.
  - The circuit breaker trips on 3 failures.
  - The timeout kills a sleeping stub.
- Manual acceptance on lakehouse-engine (real `agy`, about 20 calls):
  - Metrics: 0 invented paths, 0 dropped refs after snapping, ≥ 90% of citations exact or corrected.
  - The book must answer: how to run the tests locally; where to add a new data domain; what happens to a malformed CSV row.

## 13. Decisions and rejected alternatives

- **One bash script** (bash 3.2, `jq` optional), not a Python rewrite or a `lib/` split. It stays installable as a single symlink. *Rejected for now*: tree-sitter rewrite (§2).
- **Book by default, per-file docs opt-in.** Per-file line annotation was costly (about 1 call per file) and padded. *Rejected*: keeping both by default.
- **The script pastes code; the model only cites.** This removed invented code in the spike and cuts output tokens.
- **Plan from a cheap AI catalog**, not from pure heuristics (the planner would be blind) and not from a directory map-reduce (more calls, lossy). The map-reduce idea survives only as the >80 KB catalog fallback (§5.2).
- **Short claims with `path:line`**, not Claim/Evidence/Status blocks, which conflict with the no-fluff goal. The four evidence labels live only in UNCERTAINTIES.md.
- **DeepWiki via the script's own `curl` MCP client**, not as tools given to `agy`. Letting the agent call MCP tools would need tool permissions in headless mode, which is exactly what the yolo concern is about. *Rejected*: scraping deepwiki.com, and feeding whole `read_wiki_contents` output (1.17 MB for sqlmesh) to the model.
- **DeepWiki opt-in, not automatic.** Even for public repos the repo name leaves the machine, and most new or personal repos aren't indexed. In the 2026-10-20 probe, `ne1cc/lakehouse-engine` (private) and `sqlmesh/sqlmesh` (wrong org name) returned "Repository not found"; `TobikoData/sqlmesh` returned a 25-page tree.
- **Kept the book layout** (chapters, FILES.md) rather than `architecture.md` + `modules/` + `flows/` directories. Chapters already serve as module pages, and chapter 02 is the verified flow. Added UNCERTAINTIES.md and provenance.json as proposed.

## 14. Open questions

1. Chapter count bounds of 6–12: fine for repos of 50–500 files. Should larger monorepos get a cap per top-level package instead?
2. Should reference mode default to annotating only the top-N files by fan-in, rather than every file?

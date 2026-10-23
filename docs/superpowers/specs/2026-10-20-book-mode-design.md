# repo-summarize v2: Book Mode — Design

**Date**: 2026-10-20 · rev 3 on 2026-10-21 (second external review; backend capability tests)
**Status**: Draft, awaiting review
**Evidence**: spike on `ne1cc/lakehouse-engine` and agy capability tests, §14

## 1. Goal

Run `repo-summarize` once (it can run in the background) on an unfamiliar repo, and get a short, ordered set of Markdown files a developer reads like a book to learn **how to develop in and contribute to** that repo.

**Success test** (human, task-based, §15.2):
- (a) run and test the project;
- (b) find where to make a given change;
- (c) see what it affects;
- (d) open the cited source.

**Style**: terse, no filler, Mermaid diagrams. Every code excerpt is real source pasted by the tool.

**What the tool promises.** It checks *structure* only: a reference is in range, an identifier occurs near the cited line, an import path connects two files. It does **not** check that an explanation is true, or that an import means one piece of code calls another. Output labels say exactly what was checked (§8.1).

## 2. Scope

**v2.0 (this spec)**:
- Orientation, main-flow, subsystem and Contributing chapters;
- INDEX, FILES and UNCERTAINTIES files;
- snapshot, structured model replies, deterministic rendering;
- recoverable publishing, backend capability enforcement, secret handling;
- import extraction for the languages v1 already supports (Python, JS/TS, Lua, shell, C/C++).

**Deferred to v2.1** (tracked in the README roadmap; out of this spec's acceptance):
- per-file `--reference` walkthroughs (decided default when built: top 20 by fan-in, `--reference all` for everything);
- Go, Rust and Java/Kotlin import extractors;
- snapping excerpts to the enclosing `def`;
- automatic chapter splitting;
- cache pruning;
- a rich `--status`.

**Non-goals**:
- external research services (DeepWiki; dropped 2026-10-20);
- tree-sitter or call graphs;
- semantic claim checking;
- chat or Q&A;
- a website;
- parallel AI calls.

## 3. Implementation shape

- **One file, `bin/repo-summarize`**: Python ≥ 3.12, standard library only, run through a `#!/usr/bin/env -S uv run --script` shebang with a PEP 723 header. It installs as one symlink and replaces the bash script.
- `wrap_mermaid` and the v1 import regexes are ported.
- Internal sections, each a few functions with one job: `discover`, `snapshot`, `graph`, `backend`, `catalog`, `plan`, `attach`, `chapter`, `render`, `publish`, `cache`, `cli`.
- Tests: `uv run --with pytest pytest`.

## 4. Output

```
docs/architecture/                       published by recoverable swap (§10)
  INDEX.md  01-orientation.md  02-main-flow.md  03-<slug>.md …  NN-contributing.md
  FILES.md  UNCERTAINTIES.md  provenance.json
docs/.repo-summarize/                    private state, mode 0700, contains .gitignore "*"
  cache/  runs/<run-id>/  publish.json  lock
```

- Generated Markdown starts with `<!-- repo-summarize:v3 run=<id> -->`. JSON files carry `"generator": "repo-summarize:v3"`.
- **Reserved names** in `docs/architecture/`: `INDEX.md`, `FILES.md`, `UNCERTAINTIES.md`, `provenance.json`, `[0-9][0-9]-*.md`, `reference/`. An *unmarked* (hand-written) file with a reserved name is a hard failure: the run stops, names the file, and does not publish.
- Other unmarked files are hand-written and are copied into the new generation **at publish time**, so edits made during a run are kept.
- **v1 migration**: v1/v2-marker files in `docs/architecture/` aren't carried into the new generation, which removes them.

### 4.1 Chapters

| Role | Always present | Content |
|---|---|---|
| 01 Orientation | yes | what it is, stack, layout, install/run/test/build (from manifest commands) |
| 02 Main flow | yes | one end-to-end path from an entry point to an output |
| 03… subsystems | 0–9 | one per subsystem the planner identifies |
| last: Contributing | yes | CI gates, conventions, PR flow |

- **Subsystem count**: `target = clamp(round(f / 15), 0, 9)`, where *f* = included non-test source files. The planner may differ by ±2. The **hard maximum is 12 chapters**. A 3-file repo gets the three mandatory chapters only.
- **Fixed headings**:
  - `What this is`
  - `How it fits together` (Mermaid)
  - `How it works` (numbered steps, ≤ 8 excerpts)
  - `Where to change things`
  - `Gotchas`
  - a tool-written footer: primary files · related files · tests · related chapters · known gaps
- **Main flow** steps each name a source location and the transition to the next step. Each transition shows one of two inline labels:
  - *"import-connected; execution order not checked"*
  - *"inferred transition — no import path found"*
- **INDEX.md**: the model writes a one-paragraph overview, a system diagram, and a "why now" line per chapter. The tool writes all links and the table.
- **FILES.md** is deterministic apart from catalog purposes. Each row shows primary chapter, related chapters, tests and imported-by. It ends with a "Skipped" section grouped by reason and an "Excluded from narrative" section with reasons (§6.4).

### 4.2 Links
- **Commit links** (`github.com/<o>/<r>/blob/<sha>/<path>#L<a>-L<b>`) are used only when the file is unchanged since `HEAD` and `origin` is GitHub. They reproduce the cited source.
- **Otherwise**: a relative working-tree link labelled *"working tree — may have changed since generation"*. It's a navigation aid, not a record.
- **The pasted excerpt is the record** of what was cited. It always comes from the run snapshot.

## 5. Pipeline

| # | Stage | AI calls | Output |
|---|---|---|---|
| 0 | Discover + snapshot | 0 | snapshot, coverage counts, edges, entry points, manifest commands |
| 1 | Backend check | 0, or 1 on a fingerprint change | capability record (§11) |
| 2 | Catalog | ⌈source bytes / 60 KB⌉ | purposes and symbols |
| 3 | Plan | 1 (+1 re-ask) | chapter roles and placement |
| 4 | Attach + budget | 0 | final placement, `tests_for`, shown ranges |
| 5 | Chapters | 1 each (+1 re-ask) | structured replies (cached) |
| 6 | Index | 1 | structured reply (cached) |
| 7 | Render | 0 | all Markdown and JSON in staging |
| 8 | Validate + publish | 0 | recoverable swap |

That's about 21 calls for the spike repo, against about 124 for v1.

## 6. Stages

### 6.1 Discover and snapshot
- **File list**: `git ls-files -co --exclude-standard -z` in a git repo, `os.walk` otherwise.
- **Skip reasons**:
  - `symlink`;
  - `unsafe-path` (control characters including tab or newline, a backtick, `|`);
  - `binary` (NUL in the first 8 KB);
  - `too-large` (> 1 MB; catalog and attach truncate larger inputs);
  - `lockfile`;
  - `minified`;
  - `generated-docs` (`docs/architecture/**`, `docs/.repo-summarize/**`);
  - `secret-file` (§12);
  - `unsupported-type`.
- **Included**:
  - code extensions;
  - `yml yaml toml json sql properties ini cfg`;
  - `Dockerfile*`, `Makefile`, `justfile`;
  - root and `.github/` Markdown;
  - extensionless files with a shebang.
- **Snapshot**: included files are copied to `runs/<id>/snapshot/` (mode 0600) after line-preserving redaction (§12). sha256 is computed on the original bytes. Every later stage reads only the snapshot. The snapshot is **deleted when the run ends**, whatever the outcome. Resuming relies on cached replies, not snapshots.
- **Coverage counts** (never collapsed into one percentage):
  1. discovered
  2. included
  3. catalogued
  4. primary in a chapter
  5. related only
  6. excluded from narrative (by reason)
  7. shown in full
  8. shown partially
  9. skipped (by reason)
- **Edges**:
  - the v1 extractors (Python, JS/TS, Lua, shell, C/C++);
  - shims (≥ 80% import lines) traversed one hop;
  - ambiguous imports dropped;
  - unsupported languages listed.
- **Entry points**: name heuristics, pyproject `[project.scripts]`, `package.json` `bin`, Dockerfile `CMD`/`ENTRYPOINT`.
- **Manifest commands**: Makefile, `package.json` scripts, pyproject scripts, justfile, and Actions `run:` steps.

### 6.2 Catalog
- **Batching**: batches of ≤ 60 KB, each file capped at 400 lines. A file still over 60 KB after the cap gets its own batch, cut at the last line boundary under 60 KB. Truncation is recorded.
- **Reply contract**: JSON lines `{"path", "purpose", "symbols"}`.
  - A missing row is re-asked once alone, then becomes `(catalog failed)`.
  - A path that wasn't in the batch is discarded.

### 6.3 Plan
- **Reply**: a JSON array of `{"role": "orientation|main_flow|subsystem|contributing", "slug", "title", "why", "primary": [...], "related": [...]}`.
- **Large repos**: a catalog over 80 KB is condensed to per-directory lines (count + top 5 by fan-in). §6.4 guarantees that files missing from the condensed view are still placed.
- **Validation**:
  - Hard: unparseable; missing a mandatory role; more than 12 chapters. Re-ask once with the violations listed. If still bad, use the **deterministic fallback plan**: Orientation (root build/CI/docs files), Main flow (entry points + their direct imports), one subsystem per top-level source directory (smallest merged until within the cap), Contributing (`.github/**`, lint and CI config).
  - Repairable: unknown paths are dropped; a duplicate primary keeps its first chapter; slugs are sanitized (§9.3).
- **Plan reuse**: a cached plan is reused only while all of these hold:
  - every primary file exists;
  - the set of entry points is unchanged;
  - the set of top-level source directories is unchanged;
  - the import edge set differs by ≤ 20% (Jaccard);
  - new unassigned files make up ≤ 10% of included files.

  Otherwise it replans. `--replan` forces it.

### 6.4 Attach (placement invariant + bounded budget)

**Invariant**: every included non-test file ends Attach either **primary** in exactly one chapter, **related** to at least one chapter, or **excluded from narrative** with a reason. The reasons are: `empty`, `shim` (≥ 80% imports), `package-marker` (an `__init__`/`index` with no definitions), `catalog-failed`, `generated` (a header says "generated"). Steps, in order:

1. Entry points become primary in **02 Main flow**. Their direct imports become related to 02.
2. `tests_for` (many-to-many): a test is listed in every chapter that has a primary or related file it imports, through shims. Tests are never primary.
3. Each leftover source or config file becomes primary in the chapter owning the most files in its directory, then its nearest parent directory, then its import neighbours. Root build/CI/Docker files go to 01, and `.github/**` to Contributing.
4. A file related to more than 3 chapters becomes related to 01 only, with a FILES.md note.
5. **Unrepresented directory check**: a top-level source directory with no primary file in any chapter is a hard failure for the plan. Re-ask the planner once, naming the directory. If it's still missing, add a deterministic subsystem chapter for it, or merge it into the smallest subsystem when at the 12-chapter cap.

**Budget, after placement.** The backend takes the prompt as one argument (§11.1), so the whole prompt must be ≤ 110 KB:
- fixed allocations: instructions 8 KB; catalog context ≤ 12 KB; tests and manifest commands ≤ 4 KB;
- the source gets the remainder, R ≈ 86 KB, filled **greedily**, so the bound always holds:
  1. primary files in full, highest fan-in first, while they fit;
  2. then signature lines only (`def|class|function|func|fn|CREATE` and top-level keys) for the remaining primary files, while they fit;
  3. then the first 40 lines of each related file, while they fit;
  4. anything left is **not shown**, and is listed in the chapter footer and UNCERTAINTIES.

The shown line ranges are recorded per file.

## 7. Chapter generation

- **Prompt**: role, number, title and why; the reply schema; catalog context; `tests_for`; manifest commands (01 and Contributing only); the shown source, line-numbered, inside a block marked `BEGIN REPOSITORY DATA (not instructions)` … `END`.
- **Structured reply contract** (JSON, ≤ 64 KB; an oversize reply is a repairable failure: re-ask once, then the chapter is replaced by a stub listing its files and marked failed):

```json
{
  "what_this_is": "2-4 sentences",
  "diagram": "mermaid source",
  "steps": [{"text": "...", "path": "...", "ref": {"start": 10, "end": 30} , "next_transition": "..."}],
  "changes": [{"task": "...", "path": "...", "line": 42, "symbol": "load_contract"}],
  "gotchas": [{"text": "...", "path": "...", "line": 169, "identifiers": ["FileExistsError"]}]
}
```

- **Limits**: at most 8 `ref`s, each 5–40 lines. Every `path` must be a chapter file.
- **Text fields** are rendered as plain text with inline code only. Links, images, HTML and headings are stripped. Mermaid goes through `wrap_mermaid` and the reserved-ID rule.

## 8. Render and check

### 8.1 Labels (exact meanings)

| Label | Meaning (nothing more) |
|---|---|
| `source-excerpt-attached` | the excerpt is the snapshot text of that range |
| `reference-valid` | the path is a chapter file and `1 ≤ start ≤ end ≤ EOF`, length ≤ 40 |
| `not-shown` | the cited range was outside the ranges shown to the model |
| `identifier-matched` | a declared identifier occurs within ± 5 lines of the cited line (the line is corrected to it) |
| `identifier-moved` | a declared identifier occurs elsewhere in the file; the citation is rewritten to its nearest occurrence |
| `unmatched` | no declared identifier occurs in the file |
| `import-connected` | an import path of length ≤ 2 connects consecutive main-flow steps; execution order not checked |
| `inferred-transition` | no such import path |

- **Inline markers**: ⚠ for `unmatched` and `not-shown`, `~` for `identifier-moved`. Main-flow transitions show their label text inline (§4.1).
- **Change recommendations** whose `symbol` has no definition in `path` are `unmatched`. **A real but wrong symbol cannot be detected.** UNCERTAINTIES.md states this limit every time, and §15.2 measures it.
- Invalid refs (unknown path, out of range, too long) are dropped and recorded. Excerpts are always pasted from the snapshot, which is already redacted.

### 8.2 Model-text safety
Every model-written string goes through the same secret scanner (§12). On a hit, the string is replaced with `[removed: possible secret]` and the event is logged by location only. Absolute paths under `$HOME` that aren't inside the repo are also removed from model text.

### 8.3 Filenames
- Slugs must match `^[a-z0-9][a-z0-9-]{0,40}$`. Otherwise the slug is derived from the title.
- Filenames are `NN-<slug>.md`, with NN assigned by the tool.
- A collision gets a numeric suffix.
- Model text never becomes a path.

## 9. Caching

- **Generation key**: `sha256(stage version ‖ backend fingerprint ‖ canonical prompt bytes)`. The prompt already contains every consumed input. The value is the raw reply, stored with mode 0600.
- **Backend fingerprint**: the command as an argv list, plus `<cmd[0]> --version` output, plus the adapter version, plus the sandbox profile hash, plus `REPO_SUMMARIZE_CACHE_NAMESPACE` (default empty). Settings the tool can't observe, such as a model chosen inside agy's own config, are documented. The namespace variable lets the user force a fresh cache.
- **Rendering is never cached.** Changes to resolver, redactor or link rules apply on the next run without AI calls.
- **Plan**: governed by the reuse rules in §6.3.
- `repo-summarize --clean` deletes `docs/.repo-summarize/`.

## 10. Run lifecycle and publishing (recoverable, not atomic)

1. Take the lock at `docs/.repo-summarize/lock` (PID; a stale lock is taken over). Run **recovery** (step 6) first.
2. Discover, snapshot, run the stages, and render into `runs/<id>/staging/architecture/`.
3. Validate the staging set:
   - all mandatory chapters are present;
   - every internal link resolves;
   - no reserved-name collision with hand-written files;
   - JSON parses;
   - the placement invariant holds.
4. **Publish**, journalled in `publish.json`:
   - (a) write `{"run": id, "step": "prepared"}`;
   - (b) copy current unmarked hand-written files into staging, refusing on a reserved-name collision;
   - (c) `rename docs/architecture → runs/<id>/previous`, then journal `"moved-old"`;
   - (d) `rename staging/architecture → docs/architecture`, then journal `"done"`.
5. A capped, aborted or failed run never reaches step 4. The previous book is untouched.
6. **Recovery**, at startup or after an exception during step 4:
   - journal `moved-old` and `docs/architecture` missing → rename `previous` back;
   - journal `prepared` → discard it;
   - journal `done` → clear it.

   Between (c) and (d), `docs/architecture` briefly doesn't exist. The next run (or `--status`) restores it.
7. After `done`, delete `previous` and all run directories except the last 3 logs.

**provenance.json**:
- `run_id`, `generated_at` (ISO 8601 with offset)
- `commit`, `branch`, `dirty`
- `source_manifest_sha256`, computed from the sorted `(path, sha256)` list, including untracked files that were included
- `files_changed_during_run`
- `backend`: argv, version, fingerprint, `capabilities` (§11.2), `probe`
- `stage_versions`, `calls_by_stage`, `cache_hits_by_stage`
- `coverage` (§6.1)

## 11. Backend contract

### 11.1 Invocation (facts from the 2026-10-21 tests)
- **`agy -p` takes the very next argument as its prompt.** Flags must come before `-p`. The default is `agy --disable-slash-commands -p <prompt>`.
- **`agy` has no stdin prompt input**: `-p` without an argument prints help. The prompt is therefore one argv entry, capped at 110 KB to stay under Linux's 128 KB per-argument limit. macOS's limit is about 1 MB in total.
- **Execution**: `subprocess.run(argv, cwd=<empty temp dir>, env={PATH, HOME, LANG, TMPDIR} + REPO_SUMMARIZE_PASS_ENV, timeout=REPO_SUMMARIZE_TIMEOUT)`.

### 11.2 Capabilities: enforced vs observed

| Layer | Status for agy 1.4.3 on macOS | Evidence |
|---|---|---|
| Writes and shell commands | **Enforced by agy**: auto-denied in headless mode unless an allow-rule exists in the user's agy settings | `write_file` and `command` denied in every mode tested |
| File reads | **Not restricted by agy**: a planted file outside the working directory was read in default, `--sandbox` and `--mode plan` modes; project-level deny rules had no effect | sentinel token returned |
| OS sandbox (macOS `sandbox-exec`) | **Enforced**: a profile denying reads and writes under `$HOME` except agy's config dirs (`~/.gemini`, `~/.antigravity`, `~/.local`, `~/Library`) blocked the sentinel read; normal replies still worked | sentinel not returned; `SANDBOX-OK` reply |

**Policy**:
- **macOS**: every backend call runs under the `sandbox-exec` profile. The repo and its snapshot are under `$HOME`, so they are unreadable to the backend, which sees only its prompt. The profile's hash is part of the backend fingerprint.
- **Linux**: uses `bwrap` with an equivalent bind policy if it's installed.
- **Neither available**: the capability record says `not-sandboxed`, and the run requires `--unsafe-backend`.
- **Yolo flags** (`--dangerously-skip-permissions`, `yolo`) require `--unsafe-backend` everywhere.
- **The probe is a regression test, not authorization.** It runs on a fingerprint change: one call asking the backend to read a sentinel under `$HOME` and to write a canary.
  - It records `probe-no-access-observed` or `probe-access-observed`.
  - `probe-access-observed` under an enforced sandbox means the sandbox is broken, so the run aborts with exit 5.
- **Allow-rules**: if the user's agy settings contain allow-rules (for example `command(git status)`), they're listed in provenance, because they widen what agy may do.
- **Backend-side retention**: agy stores conversations under `~/.gemini`. The tool can't control that, and the README says so.

## 12. Secrets and data retention (best-effort, stated as such)

- **Never read**: `.env` and `.env.*` (except `.example`, `.sample`, `.template`), `*.pem`, `*.key`, `*.p12`, `*id_rsa*`, `*credentials*.json`, `secrets/**`.
- **Line-preserving redaction** at snapshot time:
  - a matching span is replaced by `[REDACTED]` on the same line;
  - for a multi-line private-key block, every line becomes `[REDACTED]`;
  - line numbers never change.
  - Patterns: AWS keys, GitHub tokens, `sk-` keys, Slack tokens, PEM blocks, and `password|secret|token|api_key = <8+ chars>`.
- **Model text** is scanned with the same patterns (§8.2).
- **Retention**:
  - `docs/.repo-summarize/` is mode 0700, and contains a `.gitignore` of `*` so it is never committed;
  - snapshots are deleted at the end of every run;
  - cached replies are 0600;
  - logs record sizes, hashes, labels and locations, **never prompt or reply bodies**;
  - `--clean` removes everything.
- **README warning**: redaction can miss secrets; repository content is sent to the configured backend; the backend may keep its own history.

## 13. Failure classes, run control, CLI

| Class | Examples | Behaviour |
|---|---|---|
| Hard | unusable plan after a re-ask (→ fallback plan), unrepresented directory after a re-ask (→ deterministic chapter), reserved-name collision, staging validation failure, sandbox unavailable without `--unsafe-backend`, probe access under an enforced sandbox | use the defined fallback if there is one; otherwise fail without publishing |
| Repairable | missing catalog row, oversize reply, unknown path, bad slug | repair and revalidate |
| Quality warning | `unmatched`, `not-shown`, `inferred-transition`, partially shown or unshown file, catalog failed | publish with an inline marker and an UNCERTAINTIES entry |

```
repo-summarize [path]     build and publish the book
  --estimate              calls per stage + prompt KB; no AI calls, no writes
  --dry-run               discovery + coverage only; no writes
  --status                last run's state; runs publish recovery if needed
  --max-calls N           stop before call N+1; exit 4; nothing published
  --force                 ignore the generation cache    --replan  ignore plan reuse
  --open                  open INDEX.md after publishing
  --clean                 delete docs/.repo-summarize/
  --unsafe-backend        allow a non-sandboxed backend or yolo flags
env: REPO_SUMMARIZE_CMD (default "agy --disable-slash-commands -p"; the prompt is appended last)
     REPO_SUMMARIZE_TIMEOUT (default 300) · REPO_SUMMARIZE_PASS_ENV · REPO_SUMMARIZE_CACHE_NAMESPACE
exit: 0 published · 1 failed · 2 usage · 3 aborted (3 consecutive call failures) · 4 capped · 5 backend unsafe
```

Option values are validated. `--filter` and `--max-files` from v1 are removed.

## 14. Evidence

**Spike** (lakehouse-engine, 2026-10-20):
- Catalog: 8 calls, 124 files, 0 missing, 0 invented.
- Plan: 1 call, 10 chapters, 0 bad paths. The CLI entry point landed in chapter 9 (§6.4 step 1 fixes this). Config files were unplaced (step 3) and tests unlinked (step 2).
- Chapter 3:
  - all 8 refs were `reference-valid`;
  - inline line numbers drifted by 1–9 lines (`identifier-matched` correction fixes this);
  - one recommendation was real but wrong (**undetectable**, §8.1);
  - one test was missed through a shim (shim traversal fixes this).
- Coverage: 158 discovered, 124 included, 34 skipped (`docs/` 32, `uv.lock`, `LICENSE`).
- The spike covered the catalog, the plan and one chapter. **No complete book has been generated yet.**

**Backend tests** (agy 1.4.3, 2026-10-21): the facts behind §11.1 and §11.2. Earlier, during the spike, agy tried to run a shell command on its own when given an empty catalog.

## 15. Testing and acceptance

### 15.1 Automated (pytest, stage-aware stub backend, fixture repos)
- **Labels**:
  - a valid ref with a false claim stays `reference-valid`, and no stronger word appears anywhere;
  - a real but wrong symbol is `identifier-matched`, with the limit stated;
  - off-by-3 / elsewhere-in-file / missing identifier → `identifier-matched` (corrected) / `identifier-moved` / `unmatched`;
  - a ref outside the shown range → `not-shown`.
- **Snapshot**: a stub edits a source file between stages. Excerpts come from the snapshot and `files_changed_during_run` is set.
- **Publishing**:
  - failure after 3 of 5 chapters, or a `--max-calls` cap → the old book is byte-identical;
  - a simulated kill between renames (c) and (d) → the next run restores the old book;
  - a hand-written `INDEX.md` → hard failure, nothing published;
  - a hand-written `notes.md` edited during the run → the edit is kept.
- **Cache**:
  - changing a neighbour title, catalog purpose, test list or command argv, the backend `--version`, the sandbox profile or the namespace → regeneration;
  - changing a redactor or link rule → re-render with no calls.
- **Placement**:
  - a whole unassigned source directory → re-ask, then a deterministic chapter;
  - an integration test importing 3 chapters' files → listed in all 3;
  - the invariant holds for every fixture.
- **Budget**: a chapter whose files are 5× the budget → the prompt stays ≤ 110 KB, and the unshown files are listed.
- **Plan roles**: a 3-file repo → exactly 3 mandatory chapters; a multi-entry-point repo → all entry points primary in 02; a stub returning 14 chapters → re-ask, then the fallback plan, capped at 12.
- **Safety**:
  - hostile repo text plus a stub that tries a sentinel read → blocked under the sandbox (macOS CI job), recorded otherwise;
  - yolo flags without `--unsafe-backend` → exit 5;
  - hostile filenames and slugs → skipped or sanitized, nothing written outside staging.
- **Secrets**: a planted token in source, and a token-shaped string in a model reply → never in a published doc, a log or the cache key material; a multi-line PEM keeps line numbers aligned.
- **No writes**: dry-run and estimate leave `git status` clean.

### 15.2 Acceptance (real agy, before release)
- **Repos**:
  - `repo-summarize` itself (the first thin end-to-end target);
  - lakehouse-engine;
  - one public third-party JS/TS repo that the reader didn't write.
- **Answer keys**: per repo, 3 prewritten tasks, each with a source-grounded answer key (for example "how do I run the tests", "where would I add X", "what does changing Y affect").
- **Scoring**: correct answer, correct source location, and time taken. Each task is scored against a README-plus-browsing baseline. Every confidently wrong recommendation is counted.
- **Re-runs**: after a moved module, a changed entry point, a changed test command and a config-only change, check which artifacts regenerate and whether the book stays correct.
- **Reported**: coverage counts, label distribution, calls, wall time.

## 16. Decisions and rejected alternatives

- **Single-file stdlib Python run by `uv`.** *Rejected*: bash (too fragile for this state and safety logic); a multi-module package (install friction).
- **The OS sandbox is the read boundary.** The tests showed agy's own flags don't restrict reads. *Rejected*: relying on the probe, on prompt delimiters, or on editing the user's global agy settings.
- **Recoverable publishing, honestly named.** *Rejected for now*: immutable generations with a pointer switch (layout and platform complexity).
- **Structured JSON replies, rendered by the tool.** *Rejected*: free-form Markdown parsing (ambiguous ownership of claims, links injected by the model).
- **Precise structural labels**, never "verified".
- **Thin end-to-end slice first** (`repo-summarize` on itself), with the deferred features in §2 coming after acceptance.
- **DeepWiki dropped.** The 2026-10-20 probe is recorded in git history (spec rev 1).
- **`--reference` scope and probe frequency**, decided 2026-10-20: top 20 by fan-in, re-probing on a fingerprint change. `--reference` itself is deferred to v2.1.

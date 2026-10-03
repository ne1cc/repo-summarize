# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [1.0.0] - 2026-10-03

First public release, extracted from a private dotfiles repository where it was developed from 2026-09-18.

### Added
- `REPO_SUMMARIZE_CMD` to choose the AI backend (default `agy -p`, no permission-skipping flag).
- `tests/smoke.sh`: offline end-to-end test using a stub backend.
- MIT license and standalone documentation.

### Included from prior development
- Pass 0 scan (no AI): repo map, entry points, heuristic import graph; per-file prompts carry callers and callees.
- Annotated walkthroughs: a comment above every line for files of 150 lines or fewer, per-block explanations above that, with "unknown" over invention.
- Reliability: failed files are logged and skipped, INDEX synthesis failure keeps the old `INDEX.md` and exits non-zero, docs regenerate when the source is newer, prompts are size-guarded, nested source links fixed.
- Progress tracking (`.progress.json`) and `--status`.
- `--dry-run`, `--filter`, `--max-files` (sampled across top-level directories), `--force`, `--open`.
- bash 3.2 compatibility (no associative arrays).
- Comprehensive coverage written to `docs/architecture/` with an AI-synthesised `INDEX.md`.

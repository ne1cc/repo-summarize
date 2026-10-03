#!/usr/bin/env bash
# Offline smoke test: runs all three passes against a throwaway repo using a stub
# AI backend (REPO_SUMMARIZE_CMD), so no model or network is needed.
set -euo pipefail

BIN="$(cd "$(dirname "$0")/.." && pwd)/bin/repo-summarize"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir "$TMP/repo" && cd "$TMP/repo"
git init -q
printf 'import b\nprint(b.x)\n' > a.py
printf 'x = 1\n' > b.py
git add -A && git -c user.name=t -c user.email=t@t commit -qm init

cat > "$TMP/stub-ai" <<'EOF'
#!/usr/bin/env bash
echo "stub summary"
EOF
chmod +x "$TMP/stub-ai"

# Pass 0 only: no AI call, must build the repo map with the import edge a.py -> b.py
"$BIN" --dry-run >/dev/null
MAP=docs/architecture/.repo-map.md
[[ -f "$MAP" ]] || fail "dry-run did not write $MAP"
grep -q 'a.py' "$MAP" && grep -q 'b.py' "$MAP" || fail "repo map is missing files"

# Full run with the stub backend
REPO_SUMMARIZE_CMD="$TMP/stub-ai" "$BIN" --force >/dev/null
[[ -f docs/architecture/a.py.md ]] || fail "per-file summary a.py.md missing"
grep -q 'stub summary' docs/architecture/a.py.md || fail "summary lacks backend output"
grep -q 'stub summary' docs/architecture/INDEX.md || fail "INDEX.md lacks backend output"
grep -q '"status": *"complete"' docs/architecture/.progress.json || fail "progress not marked complete"

# Missing backend must fail loudly
if REPO_SUMMARIZE_CMD="definitely-not-installed -p" "$BIN" --force >/dev/null 2>&1; then
  fail "missing backend should exit non-zero"
fi

echo "OK"

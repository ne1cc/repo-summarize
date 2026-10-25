#!/bin/sh
# Symlink the tool into ~/.local/bin so `repo-summarize` is on PATH.
mkdir -p "$HOME/.local/bin"
exec ln -sf "$(cd "$(dirname "$0")" && pwd)/bin/repo-summarize" "$HOME/.local/bin/repo-summarize"

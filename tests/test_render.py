import json
import re
import subprocess

import pytest

LIMIT = ("These labels check structure only: a cited symbol can exist and still be the wrong place to make a "
         "change, and that cannot be detected automatically.")
WT = "working tree — may have changed since generation"


def _lib():
    lines = [f"# line {i}" for i in range(1, 51)]
    lines[9] = "def helper():"
    lines[10] = "    return 1"
    lines[19] = 'token = "abcdefgh12345678"'
    lines[29] = "class Store:"
    return "\n".join(lines) + "\n"


FILES = {
    "app.py": "from lib import helper\n\n\ndef main():\n    return helper()\n" + "".join(f"# pad {i}\n" for i in range(20)),
    "lib.py": _lib(),
    "other.py": "def other():\n    pass\n",
    "empty.py": "",
    "tests/test_lib.py": "import lib\n",
    "README.md": "# Demo\n",
    "yarn.lock": "x\n",
    "data.bin": "x\n",
}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def book(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, FILES)
    disc = rs.discover(repo)
    snap = rs.take_snapshot(disc, tmp_path / "run")
    graph = rs.build_graph(snap, disc.included)
    n_app = len(rs.read_snapshot(snap, "app.py"))
    chs = [
        rs.Chapter("orientation", "orientation", "Orientation", "Start here.", ["README.md"]),
        rs.Chapter("main_flow", "main-flow", "Main flow", "One path.", ["app.py", "other.py"], ["lib.py"],
                   shown={"app.py": [(1, n_app)], "lib.py": [(1, 40)]}, not_shown=["other.py"]),
        rs.Chapter("subsystem", "core", "Core", "The library.", ["lib.py"], tests=["tests/test_lib.py"],
                   shown={"lib.py": [(1, 50)]}),
        rs.Chapter("contributing", "contributing", "Contributing", "Gates.", []),
    ]
    catalog = {p: rs.CatalogRow(p, f"purpose of {p}", [], False) for p in disc.included}
    catalog["other.py"] = rs.CatalogRow("other.py", "(catalog failed)", [], False, True)
    flow = {"what_this_is": "The flow.", "diagram": "```\ngraph TD\n  A --> B\n```",
            "steps": [{"text": "Start in main.", "path": "app.py", "ref": {"start": 1, "end": 5},
                       "next_transition": "calls helper"},
                      {"text": "Helper runs.", "path": "lib.py", "ref": {"start": 45, "end": 50},
                       "next_transition": 7},
                      {"text": "Other.", "path": "other.py", "ref": {"start": 1, "end": 60}}],
            "changes": [{"task": "Change the store", "path": "lib.py", "line": 30, "symbol": "Store"}],
            "gotchas": [{"text": "Off by three.", "path": "lib.py", "line": 13, "identifiers": ["helper"]},
                        {"text": "Far away.", "path": "lib.py", "line": 40, "identifiers": ["helper"]},
                        {"text": "Missing.", "path": "lib.py", "line": 5, "identifiers": ["nothing_here"]}]}
    core = {"what_this_is": "Core lib.", "diagram": "just words",
            "steps": [{"text": "Read it.", "path": "lib.py", "ref": {"start": 15, "end": 25}}],
            "changes": [{"task": "Add a helper", "path": "lib.py", "line": 12, "symbol": "helper"},
                        {"task": "Ghost", "path": "lib.py", "line": 1, "symbol": "ghost"}],
            "gotchas": []}
    orient = {"what_this_is": "A demo.", "diagram": "flowchart LR\n  a --> b", "steps": [], "changes": [],
              "gotchas": []}
    replies = {"orientation": orient, "main-flow": flow, "core": core, "contributing": None}
    index = {"overview": "A demo repo.", "diagram": "graph TD\n  x --> y", "why": ["w1", "w2", "w3", "w4"]}
    gi = rs.git_info(repo, disc.included)
    backend = rs.Backend(["agy", "-p"], 300, [], "sandbox-exec", "fp123", ["command(git status)"], [])
    stats = {"calls_by_stage": {"chapter": 4}, "cache_hits_by_stage": {"catalog": 1}}
    out = rs.render_book(chs, replies, index, snap, graph, catalog, {"empty.py": "empty"}, disc, gi, stats,
                         backend, "probe-no-access-observed", "RUN1", files_changed=["lib.py"])
    args = dict(chapters=chs, replies=replies, index_reply=index, snap=snap, graph=graph, catalog=catalog,
                exclusions={"empty.py": "empty"}, disc=disc, gi=gi, stats=stats, backend=backend,
                probe_result="probe-no-access-observed", run_id="RUN1")
    return {"rs": rs, "out": out, "chs": chs, "snap": snap, "gi": gi, "repo": repo, "args": args}


# --- labels ----------------------------------------------------------------

def test_valid_ref_is_only_reference_valid(book):
    rs, ch = book["rs"], book["chs"][1]
    md, labels = rs.resolve_ref({"start": 1, "end": 10}, "lib.py", ch, book["snap"], book["gi"], "docs/architecture")
    assert labels == ["reference-valid", "source-excerpt-attached"]
    assert "def helper():" in md and "```python" in md and "⚠" not in md


def test_ref_outside_shown_is_not_shown(book):
    rs, ch = book["rs"], book["chs"][1]
    md, labels = rs.resolve_ref({"start": 45, "end": 50}, "lib.py", ch, book["snap"], book["gi"], "docs/architecture")
    assert "not-shown" in labels and "⚠" in md
    assert "⚠ not-shown" in book["out"]["02-main-flow.md"]


def test_citations(rs):
    lines = _lib().splitlines()
    assert rs.check_citation(lines, 13, ["helper"]) == (10, "identifier-matched")
    assert rs.check_citation(lines, 40, ["helper"]) == (10, "identifier-moved")
    assert rs.check_citation(lines, 5, ["nothing_here"]) == (5, "unmatched")
    assert rs.check_citation(lines, 10, ["help"]) == (10, "unmatched")  # whole words only


def test_citation_markers_in_chapter(book):
    md = book["out"]["02-main-flow.md"]
    assert "lib.py:10" in md and "identifier-matched" in md
    assert "~ identifier-moved" in md
    assert "⚠ unmatched" in md


def test_real_but_wrong_symbol_is_matched_with_limit_stated(book):
    md = book["out"]["02-main-flow.md"]
    line = next(ln for ln in md.splitlines() if "Change the store" in ln)
    assert "identifier-matched" in line and "unmatched" not in line
    assert LIMIT in book["out"]["UNCERTAINTIES.md"]


def test_change_symbol_without_definition_is_unmatched(book):
    md = book["out"]["03-core.md"]
    assert "identifier-matched" in next(ln for ln in md.splitlines() if "Add a helper" in ln)
    assert "⚠ unmatched" in next(ln for ln in md.splitlines() if "Ghost" in ln)


def test_ref_validation(book):
    rs, ch, snap, gi = book["rs"], book["chs"][1], book["snap"], book["gi"]
    for path, ref in [("nope.py", {"start": 1, "end": 5}), ("../lib.py", {"start": 1, "end": 5}),
                      ("/etc/passwd", {"start": 1, "end": 5}), ("lib.py", {"start": 0, "end": 5}),
                      ("lib.py", {"start": 40, "end": 60}), ("lib.py", {"start": 1, "end": 41}),
                      ("README.md", {"start": 1, "end": 1})]:
        md, why = rs.resolve_ref(ref, path, ch, snap, gi, "docs/architecture")
        assert md is None and len(why) == 1, (path, ref)
    unc = book["out"]["UNCERTAINTIES.md"]
    assert "ref dropped" in unc and "other.py" in unc


def test_excerpt_from_snapshot_redacted(book):
    rs = book["rs"]
    md, _ = rs.resolve_ref({"start": 15, "end": 25}, "lib.py", book["chs"][2], book["snap"], book["gi"],
                           "docs/architecture")
    assert "[REDACTED]" in md and "abcdefgh12345678" not in md
    assert all("abcdefgh12345678" not in v for v in book["out"].values())


def test_fence_longer_than_backticks(rs, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "a.md").write_text("x\n````\ny\n````\nz\n")
    ch = rs.Chapter("subsystem", "s", "S", "w", ["a.md"], shown={"a.md": [(1, 5)]})
    gi = rs.GitInfo(None, None, False, None, set())
    md, _ = rs.resolve_ref({"start": 1, "end": 5}, "a.md", ch, rs.Snapshot(d, {}, ""), gi, "docs/architecture")
    assert "\n`````\n" in md


def test_main_flow_transition_labels(book):
    md = book["out"]["02-main-flow.md"]
    assert "calls helper" in md
    assert "import-connected; execution order not checked" in md
    assert "inferred transition — no import path found" in md
    assert md.index("import-connected") < md.index("inferred transition")


def test_model_text_cleaning(rs):
    c = lambda s: rs.clean_model_text(s, "/Users/me", "/Users/me/proj")
    assert c("see [x](http://e) and ![pic](http://i)") == "see x and pic"
    assert "<img" not in c("<img src=x>") and "&lt;img" in c("<img src=x>")
    assert c("tok ghp_" + "a" * 36) == "[removed: possible secret]"
    out = c("key at /Users/me/.ssh/id_rsa and /Users/me/proj/src/a.py")
    assert "/Users/me/.ssh" not in out and "[path removed]" in out and "/Users/me/proj/src/a.py" in out
    assert c("## Heading\n# x") == "Heading\nx"


def test_links(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x\n", "b.py": "y\n"})
    _git(repo, "remote", "add", "origin", "https://user:tok@github.com/o/r.git")
    (repo / "b.py").write_text("changed\n")
    (repo / "c.py").write_text("new\n")
    gi = rs.git_info(repo, ["a.py", "b.py", "c.py"])
    sha = _git(repo, "rev-parse", "HEAD")
    assert gi.commit == sha and gi.github == ("o", "r") and gi.dirty and gi.clean_files == {"a.py"}
    url, label = rs.source_link(gi, "a.py", 1, 5, "docs/architecture")
    assert (url, label) == (f"https://github.com/o/r/blob/{sha}/a.py#L1-L5", "")
    assert rs.source_link(gi, "b.py", 1, 5, "docs/architecture") == ("../../b.py#L1-L5", WT)
    _git(repo, "remote", "set-url", "origin", "git@github.com:o2/r2.git")
    assert rs.git_info(repo, ["a.py"]).github == ("o2", "r2")
    _git(repo, "remote", "remove", "origin")
    gi = rs.git_info(repo, ["a.py"])
    assert gi.github is None and rs.source_link(gi, "a.py", 1, 5, "docs/architecture")[1] == "(local)"
    plain = make_repo(tmp_path / "p", {"a.py": "x\n"}, git=False)
    gi = rs.git_info(plain, ["a.py"])
    assert gi.commit is None and gi.github is None and gi.clean_files == set()


def test_no_forbidden_words(book):
    for name, text in book["out"].items():
        assert not re.search(r"\b(verified|supported)\b", text, re.I), name


def test_markers_and_headings(book):
    out = book["out"]
    assert set(out) == {"INDEX.md", "01-orientation.md", "02-main-flow.md", "03-core.md", "04-contributing.md",
                        "FILES.md", "UNCERTAINTIES.md", "provenance.json"}
    for name, text in out.items():
        if name.endswith(".md"):
            assert text.startswith("<!-- repo-summarize:v3 run=RUN1 -->\n"), name
    md = out["02-main-flow.md"]
    heads = ["# 02. Main flow", "> One path.", "## What this is", "## How it fits together", "## How it works",
             "## Where to change things", "## Gotchas", "---", "**Primary files**", "**Related files**", "**Tests**",
             "**Related chapters**", "**Known gaps**"]
    pos = [md.index(h) for h in heads]
    assert pos == sorted(pos)
    assert "```mermaid\ngraph TD\n  A --> B\n```" in md
    assert "[03. Core](03-core.md)" in md  # shares lib.py
    failed = out["04-contributing.md"]
    assert "This chapter could not be generated; its files are listed below." in failed and "**Known gaps**" in failed
    core = out["03-core.md"]
    assert "```mermaid" not in core and "diagram omitted: not Mermaid" in out["UNCERTAINTIES.md"]


def test_index(book):
    md = book["out"]["INDEX.md"]
    assert "# repo" in md and "A demo repo." in md and "```mermaid\ngraph TD" in md
    assert "| # | Chapter | Why now |" in md and "[Main flow](02-main-flow.md) | w2 |" in md
    assert "(FILES.md)" in md and "(UNCERTAINTIES.md)" in md


def test_index_failed_falls_back(book):
    rs = book["rs"]
    b = book
    out = rs.render_book(b["chs"], {}, None, b["snap"], rs.Graph(set(), set(), [], [], {}), {}, {},
                         rs.discover(b["repo"]), b["gi"], {}, rs.Backend(["x"], 1, [], "none", "f", [], []),
                         "probe-no-access-observed", "R")
    assert "Overview unavailable — index generation failed." in out["INDEX.md"]
    assert "| One path. |" in out["INDEX.md"]


def test_files_md_sections(book):
    md = book["out"]["FILES.md"]
    row = next(ln for ln in md.splitlines() if ln.startswith("| `lib.py`"))
    assert "purpose of lib.py" in row and "[03. Core](03-core.md)" in row and "[02. Main flow](02-main-flow.md)" in row
    assert "`tests/test_lib.py`" in row and row.rstrip().endswith("| 2 |")
    assert "## ./" in md and "## tests/" in md
    assert "## Excluded from narrative" in md and "`empty.py` — empty" in md
    skipped = md[md.index("## Skipped"):]
    assert "### lockfile" in skipped and "`yarn.lock`" in skipped and "### unsupported-type" in skipped


def test_provenance_fields(book):
    p = json.loads(book["out"]["provenance.json"])
    for k in ("generator", "run_id", "generated_at", "commit", "branch", "dirty", "source_manifest_sha256",
              "files_changed_during_run", "backend", "stage_versions", "calls_by_stage", "cache_hits_by_stage",
              "coverage"):
        assert k in p, k
    assert p["generator"] == "repo-summarize:v3" and p["run_id"] == "RUN1"
    assert re.search(r"[+-]\d\d:\d\d$", p["generated_at"])
    assert p["files_changed_during_run"] == ["lib.py"]
    assert set(p["backend"]) == {"argv", "fingerprint", "sandbox", "allow_rules", "probe"}
    cov = p["coverage"]
    assert set(cov) == {"discovered", "included", "catalogued", "primary", "related_only", "excluded",
                        "shown_full", "shown_partial", "skipped"}
    assert cov["excluded"] == {"empty": 1} and cov["skipped"]["lockfile"] == 1
    assert cov["primary"] == 4 and cov["related_only"] == 0
    assert cov["shown_full"] == 2 and cov["shown_partial"] == 0  # lib.py full in core, app.py full


V1_DIAGRAMS = """## Summary
```
flowchart LR
  A --> B
```

```sequenceDiagram
  A->>B: hi
```

graph TD
  C --> D

```python
graph TD
```

```
a.py -> b.py
```
"""


def test_wrap_mermaid_ported(rs):
    out = rs.wrap_mermaid(V1_DIAGRAMS).splitlines()
    assert out.count("```mermaid") == 3
    assert any(a == "```mermaid" and b == "graph TD" for a, b in zip(out, out[1:]))
    assert "```python" in out
    assert out[out.index("a.py -> b.py") - 1] == "```"
    assert out[0] == "## Summary"


# --- fix round 1 -----------------------------------------------------------

def _fenced(md):
    """Lines outside any fence, and whether every fence closed."""
    outside, fence = [], None
    for ln in md.splitlines():
        m = re.match(r"\s*(`{3,}|~{3,})", ln)
        if fence is None and m:
            fence = m[1]
        elif fence is not None and m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
            fence = None
        elif fence is None:
            outside.append(ln)
    return outside, fence is None


def test_model_prose_cannot_break_structure(book):
    rs, args = book["rs"], dict(book["args"])
    reply = dict(args["replies"]["main-flow"], what_this_is="x\n```\n## y\n---\n~~~~\n===\n> q")
    args["replies"] = dict(args["replies"], **{"main-flow": reply})
    md = rs.render_book(**args)["02-main-flow.md"]
    outside, closed = _fenced(md)
    assert closed
    assert "## Where to change things" in outside and "**Known gaps**:" in outside
    assert not any(re.fullmatch(r"\s*(-{3,}|={3,})", ln) for ln in outside if ln != "---")
    assert outside.count("---") == 1  # only the footer rule
    assert not any(ln.startswith(">") and ln != "> One path." for ln in outside)


def _cells(row):
    return len(re.split(r"(?<!\\)\|", row))


def test_table_cells_escaped(book):
    rs, args = book["rs"], dict(book["args"])
    chs = [rs.Chapter(c.role, c.slug, c.title, c.why, c.primary, c.related, c.tests, c.shown, c.not_shown)
           for c in args["chapters"]]
    chs[2].title = "a|b\\"
    args["chapters"] = chs
    args["catalog"] = dict(args["catalog"], **{"lib.py": rs.CatalogRow("lib.py", "x | y", [], False)})
    args["index_reply"] = dict(args["index_reply"], why=["w1", "w|2", "w3", "w4"])
    out = rs.render_book(**args)
    for name in ("INDEX.md", "FILES.md"):
        rows = [ln for ln in out[name].splitlines() if ln.startswith("|")]
        tables, cur = [], []
        for ln in out[name].splitlines() + [""]:
            if ln.startswith("|"):
                cur.append(_cells(ln))
            elif cur:
                tables.append(cur)
                cur = []
        assert rows and all(len(set(t)) == 1 for t in tables), name
    assert r"[03. a\|b\\](03-core.md)" in out["FILES.md"]


def test_subdir_permalink(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"pkg/foo/a.py": "x\n"})
    _git(repo, "remote", "add", "origin", "git@github.com:o/r.git")
    gi = rs.git_info(repo / "pkg" / "foo", ["a.py"])
    sha = _git(repo, "rev-parse", "HEAD")
    assert gi.prefix == "pkg/foo/" and gi.clean_files == {"a.py"}
    url, label = rs.source_link(gi, "a.py", 1, 2, "docs/architecture")
    assert url == f"https://github.com/o/r/blob/{sha}/pkg/foo/a.py#L1-L2" and label == ""


def test_non_github_remote_is_working_tree(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x\n"})
    _git(repo, "remote", "add", "origin", "https://gitlab.com/o/r.git")
    gi = rs.git_info(repo, ["a.py"])
    assert gi.github is None and gi.has_remote
    assert rs.source_link(gi, "a.py", 1, 1, "docs/architecture") == ("../../a.py#L1-L1", WT)


def test_index_title_prefers_github_repo_name(rs, tmp_path):
    gi = rs.GitInfo("c" * 40, "main", False, ("o", "real-name"), set())
    ctx = rs._Ctx([], rs.Snapshot(tmp_path, {}, ""), None, gi, "/home", str(tmp_path / "worktree-dir"))
    assert rs._index_md(ctx, None)[0].startswith("# real-name\n")
    ctx.gi = rs.GitInfo(None, None, False, None, set())
    assert rs._index_md(ctx, None)[0].startswith("# worktree-dir\n")
    ctx.gi = rs.GitInfo("c" * 40, "main", False, ("o", "monorepo"), set(), "pkg/")
    assert rs._index_md(ctx, None)[0].startswith("# worktree-dir\n")  # subdirectory run: the package's name


def test_excerpt_trimmed_to_end_of_definition(rs, tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "a.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    ch = rs.Chapter("subsystem", "s", "S", "w", ["a.py"], shown={"a.py": [(1, 6)]})
    gi = rs.GitInfo(None, None, False, None, set())
    snap = rs.Snapshot(d, {}, "")
    md, labels = rs.resolve_ref({"start": 1, "end": 6}, "a.py", ch, snap, gi, "docs/architecture")
    assert "return 1" in md and "def b" not in md and "a.py:1-2" in md and labels == ["reference-valid", "source-excerpt-attached"]
    md, _ = rs.resolve_ref({"start": 2, "end": 6}, "a.py", ch, snap, gi, "docs/architecture")
    assert "def b" in md  # starts mid-function: nothing safe to snap to

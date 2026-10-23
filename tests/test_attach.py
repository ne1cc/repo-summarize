import json
import os
from pathlib import Path

import pytest


class _FakeRunner:
    def __init__(self, replies=()):
        self.replies, self.prompts = list(replies), []

    def ask_json(self, stage, prompt):
        self.prompts.append((stage, prompt))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _snap(rs, tmp_path, files):
    d = tmp_path / "snap"
    for p, c in files.items():
        (d / p).parent.mkdir(parents=True, exist_ok=True)
        (d / p).write_text(c)
    return rs.Snapshot(d, {}, "")


def _cat(rs, files, failed=()):
    return {p: rs.CatalogRow(p, "purpose", [], False, p in failed) for p in files}


def _ch(rs, role, slug, primary=(), related=()):
    return rs.Chapter(role, slug, slug, "w", list(primary), list(related))


def _book(rs, *subs, orient=(), flow=(), contrib=()):
    return [_ch(rs, "orientation", "orientation", orient), _ch(rs, "main_flow", "main-flow", flow), *subs,
            _ch(rs, "contributing", "contributing", contrib)]


def _run(rs, tmp_path, files, chapters, edges=(), entry=(), shims=(), failed=(), runner=None, fan_in=None):
    files = {p: "x = 1\n" for p in files} if not isinstance(files, dict) else files
    snap = _snap(rs, tmp_path, files)
    g = rs.Graph(set(edges), set(shims), list(entry), [], fan_in or {})
    return rs.attach(chapters, g, _cat(rs, files, failed), snap, sorted(files), runner or _FakeRunner())


def _by(chapters):
    return {c.slug: c for c in chapters}


def _check_invariant(rs, chapters, excluded, included):
    for p in included:
        if rs.is_test(p):
            assert all(p not in c.primary + c.related for c in chapters), p
            continue
        prim = sum(p in c.primary for c in chapters)
        rel = sum(p in c.related for c in chapters)
        if p in excluded:
            assert prim == rel == 0, p
        else:
            assert prim == 1 or (prim == 0 and rel >= 1), (p, prim, rel)


def test_entry_points_primary_in_main_flow(rs, tmp_path):
    files = ["src/main.py", "src/util.py", "lib/a.py"]
    plan = _book(rs, _ch(rs, "subsystem", "src", ["src/main.py", "src/util.py"]), _ch(rs, "subsystem", "lib", ["lib/a.py"]))
    chapters, excluded = _run(rs, tmp_path, files, plan, edges={("src/main.py", "src/util.py"), ("src/main.py", "lib/a.py")},
                              entry=["src/main.py"])
    b = _by(chapters)
    assert b["main-flow"].primary == ["src/main.py"]
    assert set(b["main-flow"].related) == {"src/util.py", "lib/a.py"}
    assert b["src"].primary == ["src/util.py"] and excluded == {}


def test_tests_many_to_many(rs, tmp_path):
    files = ["a/x.py", "b/y.py", "c/z.py", "tests/test_all.py", "tests/test_a.py"]
    plan = _book(rs, _ch(rs, "subsystem", "a", ["a/x.py", "tests/test_all.py"]), _ch(rs, "subsystem", "b", ["b/y.py"]),
                 _ch(rs, "subsystem", "c", ["c/z.py"], ["a/x.py"]))
    edges = {("tests/test_all.py", p) for p in ("a/x.py", "b/y.py", "c/z.py")} | {("tests/test_a.py", "a/x.py")}
    chapters, _ = _run(rs, tmp_path, files, plan, edges=edges)
    b = _by(chapters)
    assert set(b["a"].tests) == {"tests/test_all.py", "tests/test_a.py"}
    assert b["b"].tests == ["tests/test_all.py"]
    assert set(b["c"].tests) == {"tests/test_all.py", "tests/test_a.py"}  # test_a via the related a/x.py
    assert all("tests/test_all.py" not in c.primary + c.related for c in chapters)
    assert b["orientation"].tests == [] and b["main-flow"].tests == []


def test_leftover_by_directory_then_parent_then_imports(rs, tmp_path):
    files = ["pkg/a.py", "pkg/b.py", "pkg/c.py", "other/q.py", "pkg/new.py", "pkg/deep/n.py", "x/n.py"]
    s1 = _ch(rs, "subsystem", "s1", ["pkg/a.py", "pkg/b.py"])
    s2 = _ch(rs, "subsystem", "s2", ["pkg/c.py", "other/q.py"])
    chapters, _ = _run(rs, tmp_path, files, _book(rs, s1, s2), edges={("x/n.py", "other/q.py")})
    b = _by(chapters)
    assert "pkg/new.py" in b["s1"].primary  # same directory: s1 owns 2 of pkg/
    assert "pkg/deep/n.py" in b["s1"].primary  # nearest parent pkg/
    assert "x/n.py" in b["s2"].primary  # import neighbour


def test_root_build_files_to_orientation_github_to_contributing(rs, tmp_path):
    files = ["src/main.py", "Dockerfile", "Makefile", "pyproject.toml", "README.md",
             ".github/workflows/ci.yml", ".github/CODEOWNERS.md", ".pre-commit-config.yaml"]
    chapters, _ = _run(rs, tmp_path, files, _book(rs, flow=["src/main.py"]), entry=["src/main.py"])
    b = _by(chapters)
    assert set(b["orientation"].primary) == {"Dockerfile", "Makefile", "pyproject.toml", "README.md"}
    assert set(b["contributing"].primary) == {".github/workflows/ci.yml", ".github/CODEOWNERS.md", ".pre-commit-config.yaml"}


def test_related_to_many_goes_to_01(rs, tmp_path):
    files = ["lib/common.py", "lib/three.py"] + [f"s{i}/f.py" for i in range(5)]
    subs = [_ch(rs, "subsystem", "s0", ["s0/f.py", "lib/common.py", "lib/three.py"])]
    subs += [_ch(rs, "subsystem", f"s{i}", [f"s{i}/f.py"], ["lib/common.py"] + (["lib/three.py"] if i < 4 else []))
             for i in range(1, 5)]
    chapters, _ = _run(rs, tmp_path, files, _book(rs, *subs))
    b = _by(chapters)
    assert b["orientation"].related == ["lib/common.py"]
    assert all("lib/common.py" not in c.related for c in chapters if c.role != "orientation")
    assert "lib/common.py" in b["s0"].primary
    assert sum("lib/three.py" in c.related for c in chapters) == 3  # exactly 3 stays


def test_exclusion_reasons(rs, tmp_path):
    files = {
        "src/main.py": "def main():\n    pass\n",
        "src/empty.py": "",
        "src/blank.py": "  \n\n\t\n",
        "src/shim.py": "from .main import main\n",
        "src/__init__.py": "__version__ = '1'\n",
        "web/index.ts": "export function f() {}\n",
        "src/failed.py": "x = 1\n",
        "src/gen.py": "# Code generated by protoc. DO NOT EDIT.\nx = 1\n",
        "web/gen.js": "\n\n// @generated\nvar x;\n",
        "src/late.py": "\n" * 5 + "# generated, do not edit\nx = 1\n",
    }
    plan = _book(rs, _ch(rs, "subsystem", "src", list(files)), flow=["src/main.py"])
    plan[0].related = ["src/shim.py"]
    chapters, excluded = _run(rs, tmp_path, files, plan, shims=["src/shim.py"], failed=["src/failed.py"],
                              entry=["src/main.py"])
    assert excluded == {"src/empty.py": "empty", "src/blank.py": "empty", "src/shim.py": "shim",
                        "src/__init__.py": "package-marker", "src/failed.py": "catalog-failed",
                        "src/gen.py": "generated", "web/gen.js": "generated"}
    placed = {p for c in chapters for p in c.primary + c.related}
    assert not placed & set(excluded)
    assert {"web/index.ts", "src/late.py"} <= placed


def test_invariant_holds(rs, tmp_path):
    files = ["README.md", "pyproject.toml", ".github/ci.yml", "src/main.py", "src/a.py", "src/sub/b.py",
             "lib/c.py", "lib/d.py", "docs/guide.md", "tool.py", "tests/test_a.py", "lib/__init__.py"]
    contents = {p: "x = 1\n" for p in files}
    contents["lib/__init__.py"] = ""
    edges = {("src/main.py", "src/a.py"), ("tests/test_a.py", "src/a.py")}
    chapters, excluded = _run(rs, tmp_path, contents, _book(rs), edges=edges, entry=["src/main.py"],
                              runner=_FakeRunner([ValueError("bad")]))
    _check_invariant(rs, chapters, excluded, files)
    assert excluded == {"lib/__init__.py": "empty"}
    assert _by(chapters)["lib"].primary == ["lib/c.py", "lib/d.py"]  # re-ask failed -> deterministic chapter


def _stub_runner(rs, stub, monkeypatch, tmp_path, scenario):
    env = {**stub(scenario), "REPO_SUMMARIZE_PASS_ENV": "STUB_SCENARIO,STUB_LOG"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return rs.Runner(rs.make_backend(os.environ, unsafe=False), tmp_path / "state", None, False), Path(env["STUB_LOG"])


def _plan_json(chapters):
    return json.dumps([{"role": c.role, "slug": c.slug, "title": c.title, "why": c.why, "primary": c.primary,
                        "related": c.related} for c in chapters])


def test_unrepresented_dir_reask_then_chapter(rs, stub, monkeypatch, tmp_path):
    files = ["src/main.py", "lib/a.py", "worker/job.py", "worker/run.py", "docs/x.yaml"]
    plan = _book(rs, _ch(rs, "subsystem", "lib", ["lib/a.py"]), flow=["src/main.py"])
    r, log = _stub_runner(rs, stub, monkeypatch, tmp_path, {"plan": _plan_json(plan)})
    chapters, _ = _run(rs, tmp_path, files, plan, entry=["src/main.py"], runner=r)
    calls = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert len(calls) == 1 and calls[0]["stage"] == "plan"
    assert "chapter. Missing: worker.\n" in calls[0]["argv"][-1]  # docs/ holds only config, so not a source dir
    assert [c.slug for c in chapters] == ["orientation", "main-flow", "lib", "worker", "contributing"]
    w = chapters[3]
    assert w.role == "subsystem" and w.title == "worker" and set(w.primary) == {"worker/job.py", "worker/run.py"}


def test_reask_plan_adopted_when_it_covers_the_dir(rs, tmp_path):
    files = ["src/main.py", "lib/a.py", "worker/job.py"]
    plan = _book(rs, _ch(rs, "subsystem", "lib", ["lib/a.py"]), flow=["src/main.py"])
    better = json.loads(_plan_json(_book(rs, _ch(rs, "subsystem", "lib", ["lib/a.py"]),
                                         _ch(rs, "subsystem", "jobs", ["worker/job.py"]), flow=["src/main.py"])))
    runner = _FakeRunner([better])
    chapters, _ = _run(rs, tmp_path, files, plan, entry=["src/main.py"], runner=runner)
    assert [c.slug for c in chapters] == ["orientation", "main-flow", "lib", "jobs", "contributing"]
    assert len(runner.prompts) == 1 and runner.prompts[0][0] == "plan"


def test_unrepresented_at_cap_merges_into_smallest_subsystem(rs, tmp_path):
    files = ["src/main.py", "worker/job.py"] + [f"d{i}/f{j}.py" for i in range(9) for j in range(i + 2)]
    subs = [_ch(rs, "subsystem", f"d{i}", [f"d{i}/f{j}.py" for j in range(i + 2)]) for i in range(9)]
    plan = _book(rs, *subs, flow=["src/main.py"])
    assert len(plan) == rs.MAX_CHAPTERS
    chapters, _ = _run(rs, tmp_path, files, plan, entry=["src/main.py"], runner=_FakeRunner([rs.CallFailed("x")]))
    assert len(chapters) == rs.MAX_CHAPTERS
    assert "worker/job.py" in _by(chapters)["d0"].primary


def test_capped_propagates_from_reask(rs, tmp_path):
    plan = _book(rs, flow=["src/main.py"])
    with pytest.raises(rs.Capped):
        _run(rs, tmp_path, ["src/main.py", "worker/job.py"], plan, entry=["src/main.py"], runner=_FakeRunner([rs.Capped("c")]))


def _cost(rs, ch, snap):
    total = 0
    for p, ranges in ch.shown.items():
        lines = rs.read_snapshot(snap, p)
        total += len(f"=== {p} ===\n".encode())
        for s, e in ranges:
            total += sum(len(f"{n:>5}  {lines[n - 1]}\n".encode()) for n in range(s, e + 1))
    return total


def test_budget_bound(rs, tmp_path):
    filler = "    value = compute_something_long(alpha, beta, gamma, delta, epsilon, zeta)  # pad\n"
    big = "".join(("def f%d():\n" % i) if i % 100 == 0 else filler for i in range(1000))  # ~86 KB
    files = {f"src/big{i}.py": big for i in range(5)}
    files["src/nosig.py"] = filler * 1000
    files["src/small.py"] = "def s():\n    return 1\n"
    files["src/half_hi.py"] = filler * 500
    files["src/half_lo.py"] = filler * 500
    files["src/rel.py"] = "x = 1\n" * 100
    snap = _snap(rs, tmp_path, files)
    prim = [p for p in files if p != "src/rel.py"]
    ch = rs.Chapter("subsystem", "s", "S", "w", prim, ["src/rel.py"])
    g = rs.Graph(set(), set(), [], [], {"src/half_hi.py": 9, "src/half_lo.py": 1, "src/small.py": 5})
    fixed = rs.BUDGET_INSTR + rs.BUDGET_CATALOG + rs.BUDGET_TESTS
    rs.fill_budget(ch, snap, g, fixed)
    assert sum(len(c.encode()) for c in files.values()) > 5 * 86_000
    assert _cost(rs, ch, snap) <= rs.PROMPT_LIMIT - fixed
    assert ch.shown["src/half_hi.py"] == [(1, 500)] and ch.shown["src/small.py"] == [(1, 2)]
    for i in range(5):  # signatures are never dropped; spare room may add bodies around them
        got = {n for s, e in ch.shown[f"src/big{i}.py"] for n in range(s, e + 1)}
        assert set(range(1, 1001, 100)) <= got and len(got) < 1000
    assert ch.shown["src/rel.py"] == [(1, 40)]
    assert {"src/nosig.py", "src/half_lo.py"} <= set(ch.not_shown)  # lower fan-in lost the full slot
    assert set(ch.not_shown) == {p for p in prim + ["src/rel.py"] if not ch.shown.get(p)}


def test_attach_fills_budget(rs, tmp_path):
    chapters, _ = _run(rs, tmp_path, ["src/main.py", "src/a.py"], _book(rs, flow=["src/main.py", "src/a.py"]),
                       entry=["src/main.py"])
    assert _by(chapters)["main-flow"].shown == {"src/main.py": [(1, 1)], "src/a.py": [(1, 1)]}


def test_def_spans(rs):
    py = ["import x", "", "@dec", "def a():", "    return 1", "", "    # c", "def b():", "    pass", "", "X = 1",
          "class C:", "    def m(self):", "        pass"]
    assert rs._def_spans(py) == [("a", 4, 7), ("b", 8, 9), ("C", 12, 14)]
    js = ["function f() {", "  return 1;", "}", "", "function g() {", "}"]
    assert rs._def_spans(js) == [("f", 1, 3), ("g", 5, 6)]


def test_budget_adds_hot_bodies_after_signatures(rs, tmp_path):
    pad = "    hot()  # filler filler filler filler filler filler filler filler filler\n"
    big = "def hot():\n    return 1\n" + "".join(f"def cold{i}():\n" + pad * 29 for i in range(40))
    snap = _snap(rs, tmp_path, {"src/big.py": big})
    ch = rs.Chapter("subsystem", "s", "S", "w", ["src/big.py"], [])
    fixed = rs.BUDGET_INSTR + rs.BUDGET_CATALOG + rs.BUDGET_TESTS
    rs.fill_budget(ch, snap, rs.Graph(set(), set(), [], [], {}), fixed)
    shown = {n for s, e in ch.shown["src/big.py"] for n in range(s, e + 1)}
    lines = big.split("\n")
    assert _cost(rs, ch, snap) <= rs.PROMPT_LIMIT - fixed
    assert {1, 2} <= shown  # hot: the most referenced name wins first
    assert all(n in shown for n, ln in enumerate(lines, 1) if ln.startswith("def "))  # signatures never dropped
    assert len(shown) > 800 and len(shown) < len(lines)  # spare room used, still partial


def test_budget_prefers_orchestrators_over_equally_referenced_leaves(rs, tmp_path):
    pad = "    x = 1  # filler filler filler filler filler filler filler filler filler filler filler\n"
    leaves = "".join(f"def leaf{i}():\n" + pad * 28 for i in range(30))
    calls = "".join(f"    leaf{i}()\n" for i in range(30))
    big = leaves + "def orchestrate():\n" + calls + pad * 60  # called by nothing, but it calls 30 definitions
    snap = _snap(rs, tmp_path, {"src/big.py": big})
    ch = rs.Chapter("main_flow", "m", "M", "w", ["src/big.py"], [])
    rs.fill_budget(ch, snap, rs.Graph(set(), set(), [], [], {}), 100_000)  # room for ~10 KB: a few bodies at most
    start = next(n for n, ln in enumerate(big.split("\n"), 1) if ln == "def orchestrate():")
    got = {n for s, e in ch.shown["src/big.py"] for n in range(s, e + 1)}
    assert set(range(start, start + 31)) <= got  # the orchestrator's calls are visible

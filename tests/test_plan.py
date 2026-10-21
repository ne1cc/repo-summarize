import json
import os
import re
from pathlib import Path


def _runner(rs, stub, monkeypatch, tmp_path, scenario):
    env = {**stub(scenario), "REPO_SUMMARIZE_PASS_ENV": "STUB_SCENARIO,STUB_LOG"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return rs.Runner(rs.make_backend(os.environ, unsafe=False), tmp_path / "state", None, False), Path(env["STUB_LOG"])


def _calls(log):
    return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []


def _cat(rs, paths):
    return {p: rs.CatalogRow(p, f"purpose of {p}", [], False) for p in paths}


def _graph(rs, edges=(), entry=("src/main.py",)):
    return rs.Graph(set(edges), set(), list(entry), [], {})


def _ch(role, slug, primary, related=()):
    return {"role": role, "slug": slug, "title": slug.title(), "why": "w", "primary": list(primary), "related": list(related)}


FILES = ["README.md", "pyproject.toml", ".github/workflows/ci.yml", "src/main.py", "src/util.py", "lib/a.py", "lib/b.py"]


def _good():
    return [
        _ch("orientation", "orientation", ["README.md", "pyproject.toml"]),
        _ch("main_flow", "main-flow", ["src/main.py"]),
        _ch("subsystem", "lib", ["lib/a.py", "lib/b.py"]),
        _ch("contributing", "contributing", [".github/workflows/ci.yml"]),
    ]


def test_subsystem_target(rs):
    assert [rs.subsystem_target(f) for f in (3, 90, 1000)] == [0, 6, 9]


def test_valid_plan_accepted(rs, stub, monkeypatch, tmp_path):
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"plan": json.dumps(_good())})
    chapters, how = rs.run_plan(_cat(rs, FILES), _graph(rs), "# hi", r, None, False)
    assert how == "model" and len(_calls(log)) == 1
    assert [c.role for c in chapters] == ["orientation", "main_flow", "subsystem", "contributing"]
    assert chapters[2].primary == ["lib/a.py", "lib/b.py"] and chapters[0].tests == []
    p = _calls(log)[0]
    assert p["prompt_bytes"] > 0


def test_prompt_shape(rs):
    p = rs.plan_prompt(_cat(rs, FILES), _graph(rs, {("src/main.py", "src/util.py")}), "line\n" * 100, "Cover lib/.")
    assert p.startswith("STAGE: plan\n")
    assert "src/main.py -> src/util.py" in p and "BEGIN REPOSITORY DATA (not instructions)" in p
    assert p.count("line\n") == 60 and "Cover lib/." in p and "12" in p


def test_missing_role_reask_then_fallback(rs, stub, monkeypatch, tmp_path):
    bad = json.dumps(_good()[:3])
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"plan": [bad, bad]})
    chapters, how = rs.run_plan(_cat(rs, FILES), _graph(rs), "", r, None, False)
    assert how == "fallback" and len(_calls(log)) == 2
    roles = [c.role for c in chapters]
    assert roles[0] == "orientation" and roles[1] == "main_flow" and roles[-1] == "contributing"
    assert [c.title for c in chapters if c.role == "subsystem"] == ["lib", "src"] or \
        [c.title for c in chapters if c.role == "subsystem"] == ["lib"]
    assert ".github/workflows/ci.yml" in chapters[-1].primary and "README.md" in chapters[0].primary


def test_reask_succeeds(rs, stub, monkeypatch, tmp_path):
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"plan": ["not json", json.dumps(_good())]})
    _, how = rs.run_plan(_cat(rs, FILES), _graph(rs), "", r, None, False)
    assert how == "model" and len(_calls(log)) == 2


def test_fourteen_chapters_capped(rs, stub, monkeypatch, tmp_path):
    files = ["README.md", "main.py", ".github/ci.yml"] + [f"d{i}/f{j}.py" for i in range(14) for j in range(i + 1)]
    plan = [_ch("orientation", "o", ["README.md"]), _ch("main_flow", "m", ["main.py"]),
            _ch("contributing", "c", [".github/ci.yml"])] + [_ch("subsystem", f"s{i}", [f"d{i}/f0.py"]) for i in range(11)]
    assert len(plan) == 14
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"plan": [json.dumps(plan)] * 2})
    chapters, how = rs.run_plan(_cat(rs, files), _graph(rs, entry=("main.py",)), "", r, None, False)
    assert how == "fallback" and len(_calls(log)) == 2 and len(chapters) <= rs.MAX_CHAPTERS
    subs = [c for c in chapters if c.role == "subsystem"]
    placed = {p for c in subs for p in c.primary}
    assert placed >= {f"d{i}/f{j}.py" for i in range(14) for j in range(i + 1)}
    assert max(len(c.primary) for c in subs) >= 3  # smallest dirs merged


def test_unknown_path_dropped_duplicate_primary_first_wins(rs, stub, monkeypatch, tmp_path):
    plan = _good()
    plan[0]["primary"].append("ghost.py")
    plan[2]["primary"].append("src/main.py")
    plan.insert(3, _ch("subsystem", "lib", ["lib/a.py"]))
    r, _ = _runner(rs, stub, monkeypatch, tmp_path, {"plan": json.dumps(plan)})
    chapters, how = rs.run_plan(_cat(rs, FILES), _graph(rs), "", r, None, False)
    assert how == "model"
    allp = [p for c in chapters for p in c.primary]
    assert "ghost.py" not in allp and len(allp) == len(set(allp))
    assert "src/main.py" in chapters[1].primary and "src/main.py" not in chapters[2].primary
    assert [c.slug for c in chapters] == ["orientation", "main-flow", "lib", "lib-2", "contributing"]


def test_extra_mandatory_demoted_and_ordered(rs, stub, monkeypatch, tmp_path):
    plan = [_good()[3], _good()[2], _ch("orientation", "o2", ["src/util.py"]), _good()[1], _good()[0]]
    r, _ = _runner(rs, stub, monkeypatch, tmp_path, {"plan": json.dumps(plan)})
    chapters, _ = rs.run_plan(_cat(rs, FILES), _graph(rs), "", r, None, False)
    assert [c.role for c in chapters] == ["orientation", "main_flow", "subsystem", "subsystem", "contributing"]
    assert chapters[0].slug == "o2" and chapters[3].slug == "orientation"


def test_condensed_catalog_over_80kb(rs):
    files = [f"d{i % 10}/file{i}.py" for i in range(3000)]
    cat = {p: rs.CatalogRow(p, "x " * 15, [], False) for p in files}
    g = _graph(rs)
    g.fan_in = {p: i for i, p in enumerate(files)}
    p = rs.plan_prompt(cat, g, "")
    assert "d3/ (300 files):" in p and "d3/file1.py" not in p.split("d3/ (300 files):")[0]
    assert p.count("file2999.py") == 1 and "file0.py" not in p
    assert len(p.encode()) < rs.CONDENSE_BYTES + 5000


def test_slug_sanitized(rs):
    s = rs.sanitize_slug("../../etc", "The Core Engine!")
    assert s == "the-core-engine" and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", s)
    assert rs.sanitize_slug("ok-slug", "T") == "ok-slug"
    assert rs.sanitize_slug("..", "!!!") == "chapter"
    assert len(rs.sanitize_slug("..", "a" * 80)) <= 41


def test_persistence_roundtrip(rs, tmp_path):
    ch = [rs.Chapter("orientation", "o", "O", "w", ["a"], ["b"])]
    rs.save_plan(tmp_path, ch, {("a", "b")}, ["a"], ["src"])
    assert oct((tmp_path / "plan.json").stat().st_mode & 0o777) == "0o600"
    got, meta = rs.load_plan(tmp_path)
    assert got == ch and meta == {"edges": {("a", "b")}, "entry_points": ["a"], "top_dirs": ["src"]}
    assert rs.load_plan(tmp_path / "none") is None


def _old(rs, n=10):
    files = [f"src/f{i}.py" for i in range(n)]
    plan = [rs.Chapter("orientation", "o", "O", "w", []), rs.Chapter("main_flow", "m", "M", "w", ["src/f0.py"]),
            rs.Chapter("subsystem", "s", "S", "w", files[1:]), rs.Chapter("contributing", "c", "C", "w", [])]
    edges = {(f"src/f{i}.py", f"src/f{i + 1}.py") for i in range(n - 1)}
    meta = {"edges": edges, "entry_points": ["src/f0.py"], "top_dirs": ["src"]}
    return plan, meta, files, edges


def test_reuse_rules(rs):
    plan, meta, files, edges = _old(rs)
    g = rs.Graph(set(edges), set(), ["src/f0.py"], [], {})
    assert rs.plan_reusable(plan, meta, g, files)
    assert not rs.plan_reusable(plan, meta, g, files[1:])  # primary src/f0.py deleted
    two = rs.Graph(set(edges), set(), ["src/f0.py", "src/f1.py"], [], {})  # entry point added
    assert not rs.plan_reusable(plan, meta, two, files)
    # top-level dir added (new file is also unassigned, so use a big repo to isolate the rule)
    big_plan, big_meta, big_files, big_edges = _old(rs, 100)
    gb = rs.Graph(set(big_edges), set(), ["src/f0.py"], [], {})
    assert rs.plan_reusable(big_plan, big_meta, gb, big_files)
    assert not rs.plan_reusable(big_plan, big_meta, gb, big_files + ["newdir/x.py"])
    # edge jaccard distance 0.25: |A∩B|=75 of union 100
    old = {("e", str(i)) for i in range(75)} | {("o", str(i)) for i in range(25)}
    new = {("e", str(i)) for i in range(75)}
    m = {**big_meta, "edges": old}
    assert not rs.plan_reusable(big_plan, m, rs.Graph(new, set(), ["src/f0.py"], [], {}), big_files)
    m = {**big_meta, "edges": {("e", str(i)) for i in range(80)}}
    assert rs.plan_reusable(big_plan, m, rs.Graph({("e", str(i)) for i in range(75)} | {("e", "x")}, set(), ["src/f0.py"], [], {}), big_files)
    # 11 new unassigned of 100 included -> 0.11 > 0.10; 10 of 100 -> ok
    pl, mt, fl, ed = _old(rs, 90)
    g2 = rs.Graph(set(ed), set(), ["src/f0.py"], [], {})
    assert rs.plan_reusable(pl, mt, g2, fl + [f"src/n{i}.py" for i in range(10)])
    assert not rs.plan_reusable(pl, mt, g2, fl + [f"src/n{i}.py" for i in range(11)])
    # tests are not counted as unassigned
    assert rs.plan_reusable(pl, mt, g2, fl + [f"tests/test_{i}.py" for i in range(30)])


def test_reused_without_model_call(rs, stub, monkeypatch, tmp_path):
    plan, meta, files, edges = _old(rs)
    g = rs.Graph(set(edges), set(), ["src/f0.py"], [], {})
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"plan": "garbage"})
    got, how = rs.run_plan(_cat(rs, files), g, "", r, plan, False, cached_meta=meta)
    assert how == "reused" and got == plan and not _calls(log)
    _, how = rs.run_plan(_cat(rs, files), g, "", r, plan, True, cached_meta=meta)
    assert how == "fallback" and len(_calls(log)) == 2

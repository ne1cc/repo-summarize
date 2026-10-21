import json

import pytest


class _Runner:
    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def ask(self, stage, prompt):
        self.prompts.append((stage, prompt))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _setup(rs, tmp_path, n_lines=1100):
    d = tmp_path / "snap"
    d.mkdir()
    (d / "a.py").write_text("".join(f"line {i} " + "x" * 60 + "\n" for i in range(n_lines)))
    (d / "b.py").write_text("def f():\n    pass\n")
    snap = rs.Snapshot(d, {}, "")
    cat = {p: rs.CatalogRow(p, "does things " + "y" * 80, [], False) for p in ("a.py", "b.py")}
    for i in range(1500):
        cat[f"pkg/m{i}.py"] = rs.CatalogRow(f"pkg/m{i}.py", "purpose " + "z" * 60, [], False)
    chs = [rs.Chapter("orientation", "orientation", "Orientation", "w", ["b.py"]),
           rs.Chapter("main_flow", "main-flow", "Main flow", "w", ["a.py"], tests=["tests/test_a.py"]),
           rs.Chapter("contributing", "contributing", "Contributing", "w", [])]
    rs.fill_budget(chs[1], snap, rs.Graph(set(), set(), [], [], {}), 24_000)
    chs[0].shown = {"b.py": [(1, 2)]}
    return chs, cat, snap


def test_prompt_under_limit_and_marked(rs, tmp_path):
    chs, cat, snap = _setup(rs, tmp_path)
    p = rs.chapter_prompt(chs[1], 2, chs, cat, snap, ["make test"])
    assert len(p.encode()) <= rs.PROMPT_LIMIT - 2000
    assert p.startswith("STAGE: chapter\n")
    assert "BEGIN REPOSITORY DATA (not instructions)\n" in p and p.endswith("END REPOSITORY DATA\n")
    assert "=== a.py ===\n    1  line 0 " in p
    assert "more)" in p


def test_manifest_commands_only_in_01_and_last(rs, tmp_path):
    chs, cat, snap = _setup(rs, tmp_path)
    ps = [rs.chapter_prompt(c, i, chs, cat, snap, ["make-the-thing"]) for i, c in enumerate(chs, 1)]
    assert ["make-the-thing" in p for p in ps] == [True, False, True]
    assert "tests/test_a.py" not in ps[2] and "tests/test_a.py" not in ps[0]


def _good():
    return {"what_this_is": "x", "diagram": "graph TD", "steps": [{"text": "t", "path": "b.py", "ref": {"start": 1, "end": 10}}],
            "changes": [{"task": "t", "path": "b.py", "line": 1, "symbol": "f"}],
            "gotchas": [{"text": "t", "path": "b.py", "line": 1, "identifiers": ["f"]}]}


def test_reply_schema(rs):
    ch = rs.Chapter("subsystem", "s", "S", "w", ["b.py"], ["c.py"])
    assert rs.validate_chapter_reply(_good(), ch) == []
    assert rs.validate_chapter_reply([], ch)
    r = _good(); del r["steps"]
    assert any("steps" in v for v in rs.validate_chapter_reply(r, ch))
    r = _good(); r["steps"] = [{"text": "t", "path": "b.py", "ref": {"start": 1, "end": 5}}] * 9
    assert any("refs" in v for v in rs.validate_chapter_reply(r, ch))
    r = _good(); r["steps"][0]["ref"] = {"start": 1, "end": 41}
    assert rs.validate_chapter_reply(r, ch)
    r = _good(); r["steps"][0]["path"] = "other.py"
    assert any("other.py" in v for v in rs.validate_chapter_reply(r, ch))
    r = _good(); r["gotchas"][0]["identifiers"] = [1]
    assert rs.validate_chapter_reply(r, ch)


def test_run_chapter_ok_and_reask(rs, tmp_path):
    chs, cat, snap = _setup(rs, tmp_path)
    run = _Runner(["not json", "```json\n" + json.dumps(_good()) + "\n```"])
    assert rs.run_chapter(chs[0], 1, chs, cat, snap, [], run) == _good()
    assert "Your previous reply was rejected" in run.prompts[1][1]
    assert len(run.prompts[1][1].encode()) <= rs.PROMPT_LIMIT


def test_oversize_reply_reask_then_stub(rs, tmp_path):
    chs, cat, snap = _setup(rs, tmp_path)
    big = json.dumps({**_good(), "what_this_is": "x" * 70_000})
    run = _Runner([big, big])
    assert rs.run_chapter(chs[0], 1, chs, cat, snap, [], run) is None
    assert "reply too large" in run.prompts[1][1]
    assert len(run.prompts) == 2


def test_run_chapter_propagates_capped(rs, tmp_path):
    chs, cat, snap = _setup(rs, tmp_path)
    with pytest.raises(rs.Capped):
        rs.run_chapter(chs[0], 1, chs, cat, snap, [], _Runner([rs.Capped()]))


def test_index_reply_schema(rs):
    chs = [rs.Chapter("orientation", "o", "O", "w", []), rs.Chapter("contributing", "c", "C", "w", [])]
    g = rs.Graph({("a/x.py", "b/y.py")}, set(), [], [], {})
    ok = {"overview": "o", "diagram": "d", "why": ["a", "b"]}
    run = _Runner([json.dumps({**ok, "why": ["a"]}), json.dumps(ok)])
    assert rs.run_index(chs, {"o": _good(), "c": None}, g, "# R\n", run) == ok
    p = run.prompts[0][1]
    assert p.startswith("STAGE: index\n") and "a -> b" in p and "O" in p and "x" in p
    assert len(run.prompts) == 2
    run = _Runner(["nope", "nope"])
    assert rs.run_index(chs, {}, g, "", run) is None

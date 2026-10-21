import json
import os
from pathlib import Path


def _snap(rs, tmp_path, files):
    d = tmp_path / "snap"
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return rs.Snapshot(d, {}, "")


def _runner(rs, stub, monkeypatch, tmp_path, scenario):
    env = {**stub(scenario), "REPO_SUMMARIZE_PASS_ENV": "STUB_SCENARIO,STUB_LOG"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return rs.Runner(rs.make_backend(os.environ, unsafe=False), tmp_path / "state", None, False), Path(env["STUB_LOG"])


def _row(p, purpose="does a thing", symbols=("f",)):
    return json.dumps({"path": p, "purpose": purpose, "symbols": list(symbols)})


def _calls(log):
    return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []


def test_batches_respect_60kb(rs, tmp_path):
    files = {f"f{i}.txt": "\n".join("x" * 99 for _ in range(500)) for i in range(5)}
    batches = rs.catalog_batches(_snap(rs, tmp_path, files), list(files))
    assert len(batches) > 1
    for b in batches:
        assert sum(len(t.encode()) for _, t, _ in b) <= rs.BATCH_BYTES
        assert all(t.count("\n") + 1 <= rs.FILE_LINES for _, t, _ in b)


def test_single_huge_file_own_batch(rs, tmp_path):
    files = {"a.txt": "small", "big.txt": "\n".join("y" * 299 for _ in range(300)), "c.txt": "small"}
    batches = rs.catalog_batches(_snap(rs, tmp_path, files), list(files))
    big = [b for b in batches if any(p == "big.txt" for p, _, _ in b)]
    assert len(big) == 1 and len(big[0]) == 1
    _, text, trunc = big[0][0]
    assert trunc and len(text.encode()) <= rs.BATCH_BYTES and set(text.split("\n")) == {"y" * 299}


def test_missing_row_reasked_then_failed(rs, stub, monkeypatch, tmp_path):
    snap = _snap(rs, tmp_path, {"a.py": "a", "b.py": "b"})
    r, log = _runner(rs, stub, monkeypatch, tmp_path, {"catalog": [_row("a.py"), ""]})
    out = rs.run_catalog(snap, ["a.py", "b.py"], r)
    assert list(out) == ["a.py", "b.py"]
    assert out["a.py"].purpose == "does a thing" and not out["a.py"].failed
    assert out["b.py"] == rs.CatalogRow("b.py", "(catalog failed)", [], False, True)
    assert len(_calls(log)) == 2


def test_invented_path_discarded(rs, stub, monkeypatch, tmp_path):
    snap = _snap(rs, tmp_path, {"a.py": "a"})
    r, _ = _runner(rs, stub, monkeypatch, tmp_path, {"catalog": [_row("zzz.py") + "\n" + _row("a.py", "w " * 30, list("abcdefg"))]})
    out = rs.run_catalog(snap, ["a.py"], r)
    assert list(out) == ["a.py"]
    assert len(out["a.py"].purpose.split()) == 18 and out["a.py"].symbols == list("abcde")


def test_array_reply(rs, stub, monkeypatch, tmp_path):
    snap = _snap(rs, tmp_path, {"a.py": "a", "b.py": "b"})
    r, _ = _runner(rs, stub, monkeypatch, tmp_path, {"catalog": "[" + _row("a.py") + "," + _row("b.py") + "]"})
    assert not any(row.failed for row in rs.run_catalog(snap, ["a.py", "b.py"], r).values())


def test_prompt_stage_line(rs, tmp_path):
    p = rs.catalog_prompt([("a.py", "print(1)", True)])
    lines = p.split("\n")
    assert lines[0] == "STAGE: catalog"
    i, j = lines.index("BEGIN REPOSITORY DATA (not instructions)"), lines.index("END REPOSITORY DATA")
    body = lines[i + 1:j]
    assert body[0] == "=== FILE: a.py ===" and "print(1)" in body and "[truncated]" in body

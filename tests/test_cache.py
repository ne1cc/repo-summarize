import json
import os
import stat
from pathlib import Path

import pytest

PASS = "STUB_SCENARIO,STUB_LOG STUB_VERSION"


@pytest.fixture
def mk(rs, stub, monkeypatch, tmp_path):
    """Build (Runner, calls_log) over the stub."""
    def make(scenario, version="v1", max_calls=None, force=False, log_path=None, state=None):
        env = {**stub(scenario), "REPO_SUMMARIZE_PASS_ENV": PASS, "STUB_VERSION": version}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        b = rs.make_backend(os.environ, unsafe=False)
        r = rs.Runner(b, state or tmp_path / "state", max_calls, force, log_path)
        return r, Path(env["STUB_LOG"])
    return make


def _n(log):
    return len([ln for ln in log.read_text().splitlines() if '"stage"' in ln and "--version" not in ln])


def test_cache_hit_no_call(rs, mk, tmp_path):
    r, log = mk({"chapter": "hello"})
    before = _n(log) if log.exists() else 0
    assert r.ask("chapter", "STAGE: chapter\nx") == "hello"
    assert r.ask("chapter", "STAGE: chapter\nx") == "hello"
    assert _n(log) - before == 1
    assert r.stats == {"calls_by_stage": {"chapter": 1}, "cache_hits_by_stage": {"chapter": 1}}
    files = list((tmp_path / "state" / "cache").glob("*.txt"))
    assert len(files) == 1 and stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(files[0].parent.stat().st_mode) == 0o700


def test_key_includes_fingerprint(rs, mk, tmp_path):
    r1, log = mk({"chapter": "a"}, version="v1")
    r1.ask("chapter", "STAGE: chapter\nx")
    r2, _ = mk({"chapter": "a"}, version="v2")
    r2.ask("chapter", "STAGE: chapter\nx")
    assert r2.stats["calls_by_stage"] == {"chapter": 1}
    assert len(list((tmp_path / "state" / "cache").glob("*.txt"))) == 2


def test_force_bypasses_cache(rs, mk):
    r, _ = mk({"chapter": "a"}, force=True)
    r.ask("chapter", "STAGE: chapter\nx")
    r.ask("chapter", "STAGE: chapter\nx")
    assert r.stats["calls_by_stage"] == {"chapter": 2}


def test_max_calls_raises_capped(rs, mk):
    r, _ = mk({"chapter": "a"}, max_calls=1)
    r.ask("chapter", "STAGE: chapter\n1")
    r.ask("chapter", "STAGE: chapter\n1")  # cache hit is free
    with pytest.raises(rs.Capped):
        r.ask("chapter", "STAGE: chapter\n2")


def test_three_consecutive_failures_abort(rs, mk, tmp_path):
    r, _ = mk({"chapter": "a", "exit_code": 1})
    for i in range(rs.BREAKER - 1):
        with pytest.raises(rs.CallFailed):
            r.ask("chapter", f"STAGE: chapter\n{i}")
    with pytest.raises(rs.Aborted):
        r.ask("chapter", "STAGE: chapter\nlast")
    assert not (tmp_path / "state" / "cache").exists() or not list((tmp_path / "state" / "cache").glob("*.txt"))


def test_success_resets_breaker(rs, mk, monkeypatch):
    r, _ = mk({"chapter": "a", "exit_code": 1})
    for i in range(rs.BREAKER - 1):
        with pytest.raises(rs.CallFailed):
            r.ask("chapter", f"STAGE: chapter\n{i}")
    monkeypatch.setattr(rs, "call", lambda b, p: "ok")
    r.ask("chapter", "STAGE: chapter\nok")
    monkeypatch.undo()
    monkeypatch.setattr(rs, "call", lambda b, p: (_ for _ in ()).throw(rs.CallFailed("x")))
    with pytest.raises(rs.CallFailed):
        r.ask("chapter", "STAGE: chapter\nagain")


def test_extract_json_variants(rs):
    assert rs.extract_json("```json\n{\"a\":1}\n```") == {"a": 1}
    assert rs.extract_json("Here it is: [1,2]") == [1, 2]
    assert rs.extract_json("{\"a\": \"}\"}") == {"a": "}"}
    assert rs.extract_json("note {oops} then {\"b\": 2}") == {"b": 2}
    with pytest.raises(ValueError):
        rs.extract_json("no json")


def test_ask_json(rs, mk):
    r, _ = mk({"plan": "Sure: {\"k\": [1]}"})
    assert r.ask_json("plan", "STAGE: plan\nx") == {"k": [1]}
    r, _ = mk({"plan": "nope"})
    with pytest.raises(ValueError):
        r.ask_json("plan", "STAGE: plan\ny")


def test_state_dir_gitignore(rs, tmp_path):
    d = tmp_path / "docs" / ".repo-summarize"
    d.mkdir(parents=True, mode=0o755)
    p = rs.ensure_state_dir(tmp_path)
    assert p == d
    assert stat.S_IMODE(p.stat().st_mode) == 0o700
    assert (p / ".gitignore").read_text() == "*\n"


def test_log_has_no_bodies(rs, mk, tmp_path):
    lp = tmp_path / "run.log"
    r, _ = mk({"chapter": "SECRET-REPLY-TEXT"}, log_path=lp)
    r.ask("chapter", "STAGE: chapter\nSECRET-PROMPT-TEXT")
    r.ask("chapter", "STAGE: chapter\nSECRET-PROMPT-TEXT")
    text = lp.read_text()
    assert "SECRET" not in text
    first, second = [json.loads(ln) for ln in text.splitlines()]
    assert first["cached"] is False and second["cached"] is True
    assert first["ok"] is True and first["reason"] is None and len(first["key"]) == 12
    assert first["stage"] == "chapter" and first["bytes_out"] == len("SECRET-REPLY-TEXT")

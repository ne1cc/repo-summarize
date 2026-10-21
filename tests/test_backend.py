import dataclasses
import json
import os
import shlex
import sys
from pathlib import Path

import pytest

STUB_PASS = "STUB_SCENARIO,STUB_LOG STUB_VERSION"


@pytest.fixture
def backend(rs, stub, monkeypatch):
    """Build a Backend over the stub; returns (backend, log_path)."""
    def make(scenario, unsafe=False, **extra):
        env = {**stub(scenario), "REPO_SUMMARIZE_PASS_ENV": STUB_PASS, **extra}
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return rs.make_backend(os.environ, unsafe), Path(env["STUB_LOG"])
    return make


def _calls(log):
    return [json.loads(ln) for ln in log.read_text().splitlines()]


def test_prompt_is_last_argv(rs, backend, tmp_path):
    b, log = backend({"chapter": "ok"})
    prompt = "STAGE: chapter\n--not-a-flag"
    assert rs.call(b, prompt) == "ok"
    assert _calls(log)[-1]["argv"][-1] == prompt
    assert shlex.split(rs.DEFAULT_CMD) == ["agy", "--disable-slash-commands", "-p"]
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "agy").write_text("#!/bin/sh\necho fake-agy\n")
    (fake / "agy").chmod(0o755)
    assert rs.make_backend({"PATH": str(fake)}, False).argv == ["agy", "--disable-slash-commands", "-p"]


def test_minimal_env(rs, backend, monkeypatch):
    monkeypatch.setenv("FOO", "1")
    b, log = backend({"chapter": "ok"})
    rs.call(b, "STAGE: chapter")
    entry = _calls(log)[-1]
    # Not a subset check: macOS's /usr/bin/python3 xcrun shim adds SDKROOT, CPATH, ... itself.
    assert not {"FOO", "REPO_SUMMARIZE_CMD", "REPO_SUMMARIZE_PASS_ENV"} & set(entry["env_keys"])
    assert {"PATH", "HOME", "STUB_SCENARIO", "STUB_LOG"} <= set(entry["env_keys"])
    b, log = backend({"chapter": "ok"}, REPO_SUMMARIZE_PASS_ENV=STUB_PASS + ",FOO")
    rs.call(b, "STAGE: chapter")
    assert _calls(log)[-1]["env"]["FOO"] == "1"


def test_cwd_is_empty_tempdir(rs, backend):
    b, log = backend({"chapter": "ok"})
    rs.call(b, "STAGE: chapter")
    entry = _calls(log)[-1]
    cwd = Path(entry["cwd"]).resolve()
    assert entry["cwd_files"] == []
    for outside in (Path(__file__).resolve().parent.parent, Path.home().resolve()):
        assert outside not in (cwd, *cwd.parents)
    assert not cwd.exists()


def test_yolo_refused(rs, backend, monkeypatch):
    for cmd in ("agy --dangerously-skip-permissions -p", "agy --yolo -p"):
        with pytest.raises(rs.BackendUnsafe):
            backend({}, REPO_SUMMARIZE_CMD=cmd)
    b, _ = backend({}, unsafe=True, REPO_SUMMARIZE_CMD=f"{shlex.quote(sys.executable)} --yolo")
    assert "--yolo" in b.argv
    monkeypatch.setattr(rs, "detect_sandbox", lambda: "none")
    with pytest.raises(rs.BackendUnsafe):
        backend({})
    assert backend({}, unsafe=True)[0].sandbox == "none"


def test_timeout_and_failures(rs, backend):
    cases = [
        ({"sleep": 3, "chapter": "late"}, "timeout"),
        ({"exit_code": 1}, "exit 1"),
        ({"stderr": "write_file auto-denied", "chapter": "x"}, "tool-denied"),
        ({"stderr": "Please authenticate first", "exit_code": 1}, "auth"),
        ({"stderr": "Error: Not logged in"}, "auth"),
        ({"chapter": "  \n"}, "empty"),
    ]
    for scenario, reason in cases:
        b, _ = backend(scenario, REPO_SUMMARIZE_TIMEOUT="1")
        assert b.timeout == 1
        with pytest.raises(rs.CallFailed) as e:
            rs.call(b, "STAGE: chapter\nsecret-prompt-body")
        assert e.value.reason == reason
        assert "secret-prompt-body" not in str(e.value)


def test_missing_backend(rs, backend):
    with pytest.raises(rs.BackendMissing):
        backend({}, REPO_SUMMARIZE_CMD="nonexistent-xyz -p")
    with pytest.raises(rs.BackendMissing):
        backend({}, REPO_SUMMARIZE_CMD="")


def test_fingerprint_changes(rs, backend, monkeypatch):
    base = backend({})[0].fingerprint
    assert backend({})[0].fingerprint == base
    assert backend({}, REPO_SUMMARIZE_CMD=os.environ["REPO_SUMMARIZE_CMD"] + " -x")[0].fingerprint != base
    assert backend({}, STUB_VERSION="stub-2")[0].fingerprint != base
    assert backend({}, REPO_SUMMARIZE_CACHE_NAMESPACE="ns")[0].fingerprint != base
    monkeypatch.delenv("REPO_SUMMARIZE_CACHE_NAMESPACE")
    monkeypatch.setenv("STUB_VERSION", "stub-1")
    assert backend({})[0].fingerprint == base
    monkeypatch.setattr(rs, "sandbox_profile", lambda home: "(version 1)(allow default)")
    if rs.detect_sandbox() == "sandbox-exec":
        assert backend({})[0].fingerprint != base


def test_sandbox_profile_escapes_home(rs):
    prof = rs.sandbox_profile(Path('/nonexistent/we"ird\\home'))
    assert '(deny file-read* (subpath "/nonexistent/we\\"ird\\\\home"))' in prof
    assert '(literal "/nonexistent/we\\"ird\\\\home")' in prof
    assert '(subpath "/nonexistent/we\\"ird\\\\home/.gemini")' in prof


def test_bwrap_prefix(rs, tmp_path):
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    (home / ".local").mkdir()
    assert rs.sandbox_argv("bwrap", home, "/tmp/cwd") == [
        "bwrap", "--ro-bind", "/", "/", "--tmpfs", str(home),
        "--bind", str(home / ".gemini"), str(home / ".gemini"),
        "--ro-bind", str(home / ".local"), str(home / ".local"),
        "--dev", "/dev", "--proc", "/proc", "--chdir", "/tmp/cwd", "--"]
    assert rs.sandbox_argv("none", home, "/tmp/cwd") == []


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")
def test_sandbox_blocks_home_read(rs, backend, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    sentinel = home / "sentinel.txt"
    sentinel.write_text("TOKEN-5f2a")
    monkeypatch.setenv("HOME", str(home))
    b, _ = backend({"read_path": str(sentinel)})
    assert b.sandbox == "sandbox-exec"
    assert "TOKEN-5f2a" not in rs.call(b, "STAGE: chapter")
    # Control: the same stub does read it without the sandbox.
    assert "TOKEN-5f2a" in rs.call(dataclasses.replace(b, sandbox="none"), "STAGE: chapter")


def test_probe_access_observed(rs, backend, tmp_path):
    b, log = backend({"probe": "here: tok-123"})
    assert rs.probe(b, tmp_path, token="tok-123") == "probe-access-observed"
    assert _calls(log)[-1]["stage"] == "probe"
    assert not list(tmp_path.glob(".repo-summarize-probe-*"))
    b, _ = backend({"probe": "done", "mutate": {"path": "canary", "content": "x"}})
    assert rs.probe(b, tmp_path, token="tok-123") == "probe-access-observed"


def test_probe_no_access_observed(rs, backend, tmp_path):
    b, log = backend({"probe": "I cannot read that file."})
    assert rs.probe(b, tmp_path, token="tok-xyz") == "probe-no-access-observed"
    assert "tok-xyz" not in _calls(log)[-1]["argv"][-1]
    assert not list(tmp_path.glob(".repo-summarize-probe-*"))
    b, _ = backend({"probe": "x", "stderr": "write_file auto-denied"})
    assert rs.probe(b, tmp_path) == "probe-no-access-observed"


def test_allow_rules_reported(rs, backend, tmp_path, monkeypatch):
    home = tmp_path / "home"
    cfg = home / ".gemini" / "antigravity-cli"
    cfg.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert backend({})[0].allow_rules == []
    (cfg / "settings.json").write_text("{not json")
    assert backend({})[0].allow_rules == []
    (cfg / "settings.json").write_text(json.dumps({"permissions": {"allow": ["command(git status)"]}}))
    assert backend({})[0].allow_rules == ["command(git status)"]

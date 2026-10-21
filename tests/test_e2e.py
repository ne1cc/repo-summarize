import json
import subprocess
from pathlib import Path

from tests.conftest import APP, BOOK_FILES, TOKEN, book_scenario

ARCH = "docs/architecture"
STATE = "docs/.repo-summarize"


def _all_text(d: Path) -> str:
    return "".join(p.read_text(errors="replace") for p in d.rglob("*") if p.is_file())


def test_e2e_stub_book(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    code, calls = tool.run(repo)
    assert code == rs.EXIT_OK
    arch = repo / ARCH
    for name in ("INDEX.md", "FILES.md", "UNCERTAINTIES.md", "provenance.json"):
        assert (arch / name).is_file(), name
    assert len(list(arch.glob("[0-9][0-9]-*.md"))) >= 3
    assert sorted(set(calls)) == ["catalog", "chapter", "index", "plan"]
    assert TOKEN not in _all_text(arch) and TOKEN not in _all_text(repo / STATE)
    state = repo / STATE
    assert not (state / "lock").exists() and not list(state.glob("runs/*/snapshot"))
    assert not (state / "publish.json").exists() and not list(state.glob("runs/*/previous"))
    prov = json.loads((arch / "provenance.json").read_text())
    assert prov["generator"] == "repo-summarize:v3" and prov["files_changed_during_run"] == []


def test_snapshot_consistency(rs, tool):
    repo = tool.repo()
    tool.no_sandbox()
    tool.scenario(book_scenario(mutate_on_stage={"chapter": {"path": str(repo / "app.py"),
                                                             "content": "CHANGED\n" * 10}}))
    code, _ = tool.run(repo, "--unsafe-backend")
    assert code == rs.EXIT_OK
    md = (repo / ARCH / "02-main-flow.md").read_text()
    assert APP.splitlines()[0] in md and "CHANGED" not in md
    prov = json.loads((repo / ARCH / "provenance.json").read_text())
    assert prov["files_changed_during_run"] == ["app.py"]


def test_cache_invalidation_matrix(rs, tool, monkeypatch):
    repo = tool.repo()
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://example.com/r.git"], check=True)
    tool.scenario(book_scenario())
    code, calls = tool.run(repo)
    assert code == 0 and len(calls) == 8
    # 1. no change → no calls
    assert tool.run(repo) == (0, [])
    # 2. one subsystem file → its catalog batch, its chapter, the index
    (repo / "pkg_b/extra.py").write_text("def extra():\n    return 3\n")
    code, calls = tool.run(repo)
    assert code == 0 and sorted(calls) == ["catalog", "chapter", "index"]
    # 3. a link rule → re-rendered with no calls
    monkeypatch.setattr(rs, "WORKING_TREE", "a changed link label")
    assert tool.run(repo) == (0, [])
    assert "a changed link label" in (repo / ARCH / "02-main-flow.md").read_text()
    # 4. backend --version → everything regenerates except the reused plan
    monkeypatch.setenv("STUB_VERSION", "stub-2")
    code, calls = tool.run(repo)
    assert code == 0 and sorted(calls) == ["catalog"] + ["chapter"] * 5 + ["index"]


def test_dry_run_and_estimate_no_writes(rs, tool, capsys):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo, "--dry-run") == (0, [])
    out = capsys.readouterr().out
    assert "included" in out and "secret-file" in out and "app.py" in out
    assert tool.run(repo, "--estimate") == (0, [])
    out = capsys.readouterr().out
    for word in ("catalog", "plan", "chapters", "index", "total"):
        assert word in out
    porcelain = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True)
    assert porcelain.stdout == ""


def test_clean_removes_state(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0 and (repo / STATE).is_dir()
    assert tool.run(repo, "--clean") == (0, [])
    assert not (repo / STATE).exists() and (repo / ARCH / "INDEX.md").is_file()


def test_tiny_repo_three_chapters(rs, tool):
    files = {"README.md": "# Tiny\n", "main.py": "import util\n\nutil.go()\n", "util.py": "def go():\n    pass\n"}
    repo = tool.repo(files)
    tool.scenario(book_scenario(files=files, plan=None, n_chapters=3) | {"plan": "no plan"})
    code, _ = tool.run(repo)
    assert code == 0
    assert sorted(p.name for p in (repo / ARCH).glob("[0-9][0-9]-*.md")) == [
        "01-orientation.md", "02-main-flow.md", "03-contributing.md"]


def test_no_commits_repo(rs, tool):
    repo = tool.repo(commit=False)
    tool.scenario(book_scenario())
    code, _ = tool.run(repo)
    assert code == rs.EXIT_OK
    assert json.loads((repo / ARCH / "provenance.json").read_text())["commit"] is None
    text = _all_text(repo / ARCH)
    assert "github.com" not in text
    assert "](../../app.py#L1-L5)" in (repo / ARCH / "02-main-flow.md").read_text()


def test_ctrl_c_mid_run(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario(sigint_on_stage="chapter"))
    code, calls = tool.run(repo)
    assert code == rs.EXIT_ABORT
    assert calls[-1] == "chapter"
    assert not (repo / ARCH).exists()
    assert not (repo / STATE / "lock").exists()
    assert list((repo / STATE / "cache").glob("*.txt"))
    assert not list((repo / STATE).glob("runs/*/snapshot"))


# --- main()-level exits -------------------------------------------------------

def test_missing_backend_exit_1_lock_released(rs, tool, capsys):
    repo = tool.repo()
    tool.scenario(book_scenario(), REPO_SUMMARIZE_CMD="no-such-backend-xyz -p")
    assert tool.run(repo)[0] == rs.EXIT_FAIL
    assert "no-such-backend-xyz" in capsys.readouterr().err
    assert not (repo / STATE / "lock").exists() and not (repo / ARCH).exists()


def test_probe_access_exit_5(rs, tool, monkeypatch, capsys):
    repo = tool.repo()
    monkeypatch.setattr(rs.secrets, "token_hex", lambda n=16: "ab" * n)
    tool.scenario(book_scenario(probe="ab" * 16))
    assert tool.run(repo) == (rs.EXIT_UNSAFE, [])
    err = capsys.readouterr().err
    assert "$HOME" in err and "stopped" in err
    assert not (repo / ARCH).exists() and not (repo / STATE / "lock").exists()
    rec = repo / STATE / "probe.json"
    assert not rec.exists() or "probe-access-observed" not in rec.read_text()


def test_live_lock_exit_1(rs, tool, capsys):
    import os
    repo = tool.repo()
    tool.scenario(book_scenario())
    state = rs.ensure_state_dir(repo)
    (state / "lock").write_text(str(os.getppid()))
    assert tool.run(repo) == (rs.EXIT_FAIL, [])
    assert "another run is in progress" in capsys.readouterr().err
    (state / "lock").write_text("999999999")  # stale → taken over
    assert tool.run(repo)[0] == rs.EXIT_OK and not (state / "lock").exists()


def test_bad_timeout_is_usage(rs, tool, monkeypatch):
    repo = tool.repo()
    monkeypatch.setenv("REPO_SUMMARIZE_TIMEOUT", "soon")
    assert rs.main([str(repo)]) == rs.EXIT_USAGE


def test_e2e_tool_denied_degrades_not_aborts(rs, tool):
    denied = "jetski: no output produced - a tool required permission, so it was auto-denied."
    repo = tool.repo()
    tool.scenario(book_scenario(stderr_by_stage={"plan": [denied], "chapter": [denied, denied, ""]}))
    code, calls = tool.run(repo)
    assert code == rs.EXIT_OK
    arch = repo / ARCH
    assert (arch / "INDEX.md").is_file()
    assert calls.count("plan") >= 2 and calls.count("chapter") >= 3
    unc = (arch / "UNCERTAINTIES.md").read_text()
    assert "generation failed; this chapter lists its files only" in unc
    assert sum("lists its files only" in p.read_text() for p in arch.glob("[0-9][0-9]-*.md")) == 1

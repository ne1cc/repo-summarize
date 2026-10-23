import json
import os
from pathlib import Path

from tests.conftest import book_scenario

ARCH = "docs/architecture"
STATE = "docs/.repo-summarize"


def _tree(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_failure_mid_run_keeps_old_book(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0
    old = _tree(repo / ARCH)
    os.remove(tool.env["STUB_LOG"])
    tool.scenario(book_scenario(fail_after={"chapter": 3}))
    code, calls = tool.run(repo, "--force")
    assert code in (rs.EXIT_ABORT, rs.EXIT_FAIL)
    assert calls.count("chapter") == 6 and "index" not in calls
    assert _tree(repo / ARCH) == old


def test_capped_run_no_publish_then_resume(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    code, calls = tool.run(repo, "--max-calls", "4")
    assert code == rs.EXIT_CAPPED and len(calls) == 4
    assert not (repo / ARCH).exists()
    code, calls = tool.run(repo)
    assert code == 0 and calls == ["chapter"] * 3 + ["index"]


def test_kill_between_renames_recovered(rs, tool, monkeypatch):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0
    old = _tree(repo / ARCH)
    real_rename, real_recover = rs.Path.rename, rs.recover

    def rename(self, target):
        if self.parts[-2:] == ("staging", "architecture"):
            raise KeyboardInterrupt
        return real_rename(self, target)

    # 1. Simulated hard kill between (c) and (d): no in-process recovery runs
    monkeypatch.setattr(rs.Path, "rename", rename)
    monkeypatch.setattr(rs, "recover", lambda root, state: None)
    assert tool.run(repo)[0] == rs.EXIT_ABORT
    assert not (repo / ARCH).exists()
    assert json.loads((repo / STATE / "publish.json").read_text())["step"] == "moved-old"
    # 2. The next invocation (--status) restores the old book
    monkeypatch.setattr(rs.Path, "rename", real_rename)
    monkeypatch.setattr(rs, "recover", real_recover)
    assert tool.run(repo, "--status") == (0, [])
    assert _tree(repo / ARCH) == old
    assert not (repo / STATE / "publish.json").exists()


def test_exception_in_publish_recovers_in_process(rs, tool, monkeypatch):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0
    old = _tree(repo / ARCH)
    real_rename = rs.Path.rename

    def rename(self, target):
        if self.parts[-2:] == ("staging", "architecture"):
            raise OSError("disk full")
        return real_rename(self, target)

    monkeypatch.setattr(rs.Path, "rename", rename)
    assert tool.run(repo)[0] == rs.EXIT_FAIL
    assert _tree(repo / ARCH) == old and not (repo / STATE / "publish.json").exists()


def test_handwritten_reserved_name_fails(rs, tool, capsys):
    repo = tool.repo()
    (repo / ARCH).mkdir(parents=True)
    (repo / ARCH / "INDEX.md").write_text("my own index\n")
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == rs.EXIT_FAIL
    assert "INDEX.md" in capsys.readouterr().err
    assert _tree(repo / ARCH) == {"INDEX.md": b"my own index\n"}
    assert not (repo / STATE / "publish.json").exists()


def test_handwritten_file_edited_during_run_kept(rs, tool):
    repo = tool.repo()
    notes = repo / ARCH / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("old notes\n")
    (repo / ARCH / "img").mkdir()
    (repo / ARCH / "img" / "a.txt").write_text("nested\n")
    tool.no_sandbox()
    tool.scenario(book_scenario(mutate={"path": str(notes), "content": "edited during run\n"}))
    assert tool.run(repo, "--unsafe-backend")[0] == 0
    assert notes.read_text() == "edited during run\n"
    assert (repo / ARCH / "img" / "a.txt").read_text() == "nested\n"
    assert (repo / ARCH / "INDEX.md").is_file()


def test_v1_marker_docs_removed(rs, tool):
    repo = tool.repo()
    arch = repo / ARCH
    arch.mkdir(parents=True)
    (arch / "old-summary.md").write_text("# Architecture Summary: `src`\n\nold\n")
    (arch / "v2.md").write_text("<!-- repo-summarize:v2 run=x -->\n# Old\n")
    (arch / "keep.md").write_text("mine\n")
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0
    assert not (arch / "old-summary.md").exists() and not (arch / "v2.md").exists()
    assert (arch / "keep.md").read_text() == "mine\n"


def test_keeps_last_runs(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    for _ in range(5):
        assert tool.run(repo)[0] == 0
    runs = list((repo / STATE / "runs").iterdir())
    assert len(runs) == rs.KEEP_RUNS and all((r / "log.jsonl").is_file() for r in runs)


def test_validate_staging(rs):
    chs = [rs.Chapter("orientation", "orientation", "O", "w", ["a.py"]),
           rs.Chapter("main_flow", "main-flow", "M", "w", ["a.py"]),
           rs.Chapter("contributing", "contributing", "C", "w", [])]
    files = {"01-orientation.md": "[x](02-main-flow.md) [y](missing.md) [z](../../a.py#L1-L2)\n"
                                  "```python\nx[0](y)\n```\n`[q](nope.md)`",
             "02-main-flow.md": "", "INDEX.md": "", "provenance.json": "{bad"}
    bad = rs.validate_staging(files, chs)
    text = "\n".join(bad)
    assert "03-contributing.md" in text and "missing.md" in text and "provenance.json" in text
    assert "a.py" in text  # primary twice
    assert "nope.md" not in text and "(y)" not in text and "../../a.py" not in text


def _journal_fails_on_moved_old(rs, monkeypatch):
    real = rs._journal

    def journal(state, run_id, step):
        if step == "moved-old":
            raise OSError("no space left on device")
        return real(state, run_id, step)

    monkeypatch.setattr(rs, "_journal", journal)
    return real


def _book_with_notes(rs, tool):
    repo = tool.repo()
    tool.scenario(book_scenario())
    assert tool.run(repo)[0] == 0
    (repo / ARCH / "notes.md").write_text("mine\n")
    return repo, _tree(repo / ARCH)


def test_journal_failure_after_move_restored_in_process(rs, tool, monkeypatch):
    repo, old = _book_with_notes(rs, tool)
    _journal_fails_on_moved_old(rs, monkeypatch)
    assert tool.run(repo)[0] == rs.EXIT_FAIL
    assert _tree(repo / ARCH) == old and not (repo / STATE / "publish.json").exists()


def test_journal_failure_after_move_restored_next_run(rs, tool, monkeypatch):
    repo, old = _book_with_notes(rs, tool)
    real_journal = _journal_fails_on_moved_old(rs, monkeypatch)
    real_recover = rs.recover
    monkeypatch.setattr(rs, "recover", lambda root, state: None)
    assert tool.run(repo)[0] == rs.EXIT_FAIL
    assert not (repo / ARCH).exists()
    assert json.loads((repo / STATE / "publish.json").read_text())["step"] == "prepared"
    monkeypatch.setattr(rs, "_journal", real_journal)
    monkeypatch.setattr(rs, "recover", real_recover)
    assert tool.run(repo, "--status") == (0, [])
    assert _tree(repo / ARCH) == old and not (repo / STATE / "publish.json").exists()

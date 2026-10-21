import pytest

from tests.conftest import TOOL


def test_help_exits_0(rs):
    with pytest.raises(SystemExit) as e:
        rs.main(["--help"])
    assert e.value.code == 0


@pytest.mark.parametrize("argv", [["--max-calls", "x"], ["--max-calls"]])
def test_max_calls_requires_int(rs, argv):
    assert rs.main(argv) == 2


def test_removed_v1_flags_rejected(rs):
    assert rs.main(["--filter", "a"]) == 2


def test_valid_invocation_ok(rs, tmp_path):
    assert rs.main(["--dry-run", "--max-calls", "3", str(tmp_path)]) == rs.EXIT_OK


def test_shebang_and_pep723():
    text = TOOL.read_text()
    assert text.splitlines()[0] == "#!/usr/bin/env -S uv run --script"
    assert 'requires-python = ">=3.12"' in text


def test_constants(rs):
    assert (rs.PROMPT_LIMIT, rs.MARKER, rs.DEFAULT_CMD) == (
        110_000, "repo-summarize:v3", "agy --disable-slash-commands -p")


def test_stub_backend(stub, tmp_path):
    import json
    import shlex
    import subprocess
    env = stub({"plan": ["a", "b"]})
    cmd = shlex.split(env["REPO_SUMMARIZE_CMD"])
    child = {**env, "PATH": "/usr/bin"}

    def run():
        return subprocess.run([*cmd, "STAGE: plan\nx"], env=child, capture_output=True, text=True).stdout

    assert [run(), run()] == ["a", "b"]
    first = json.loads(open(env["STUB_LOG"]).readline())
    assert first["stage"] == "plan" and "PATH" in first["env"]
    v = subprocess.run([*cmd, "--version"], env=child, capture_output=True, text=True).stdout
    assert v.strip() == "stub-1"

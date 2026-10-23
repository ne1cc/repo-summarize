import importlib.util
import json
import shlex
import shutil
import subprocess
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "bin" / "repo-summarize"
STUB = Path(__file__).resolve().parent / "stub_backend.py"


def _load():
    loader = SourceFileLoader("repo_summarize", str(TOOL))
    spec = importlib.util.spec_from_loader("repo_summarize", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


rs = _load()


@pytest.fixture(name="rs")
def rs_fixture():
    return rs


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def make_repo():
    def make(tmp_path, files, git=True, commit=True):
        repo = Path(tmp_path) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content)
        if git:
            _git(repo, "init", "-q")
            _git(repo, "add", "-A")
            if commit:
                _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
        return repo

    return make


@pytest.fixture
def stub(tmp_path):
    # sandbox-exec denies reads under $HOME, so stub files live outside it.
    if Path.home() in (tmp_path, *tmp_path.parents):
        base = Path(tempfile.mkdtemp(dir="/tmp"))
    else:
        base = Path(tempfile.mkdtemp(dir=tmp_path))
    py = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else shutil.which("python3")
    script = base / "stub_backend.py"
    shutil.copy(STUB, script)

    def make(scenario):
        (base / "scenario.json").write_text(json.dumps(scenario))
        return {
            "REPO_SUMMARIZE_CMD": shlex.join([py, str(script)]),
            "STUB_SCENARIO": str(base / "scenario.json"),
            "STUB_LOG": str(base / "calls.jsonl"),
        }

    yield make
    shutil.rmtree(base, ignore_errors=True)


# --- end-to-end fixture -------------------------------------------------------

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0" * 2
APP = "".join(["from pkg_a import core\n", "from pkg_b.util import helper\n", "\n", "\n", "def main():\n",
               "    return helper(core.run())\n", "\n", "\n", "if __name__ == '__main__':\n", "    main()\n"])
BOOK_FILES = {
    "README.md": "# Demo\n\nA demo repository.\n",
    "app.py": APP,
    "pkg_a/__init__.py": "from .core import run\n",
    "pkg_a/core.py": "def run():\n    return 1\n",
    "pkg_b/util.py": "def helper(x):\n    return x + 1\n",
    "pkg_b/extra.py": "def extra():\n    return 2\n",
    "tests/test_core.py": "from pkg_a.core import run\n\n\ndef test_run():\n    assert run() == 1\n",
    "config.yaml": "name: demo\n",
    "Dockerfile": 'FROM python:3.12\nCMD ["python", "app.py"]\n',
    "Makefile": "test:\n\tpytest\n",
    "scripts/run": "#!/bin/sh\necho hi\n",
    ".env": f"TOKEN={TOKEN}\n",
}
BOOK_PLAN = [
    {"role": "orientation", "slug": "orientation", "title": "Orientation", "why": "Start here.",
     "primary": ["README.md", "config.yaml", "Dockerfile", "Makefile"]},
    {"role": "main_flow", "slug": "main-flow", "title": "Main flow", "why": "One path.", "primary": ["app.py"]},
    {"role": "subsystem", "slug": "core", "title": "Core", "why": "Core logic.", "primary": ["pkg_a/core.py"]},
    {"role": "subsystem", "slug": "util", "title": "Utilities", "why": "Helpers.",
     "primary": ["pkg_b/util.py", "pkg_b/extra.py", "scripts/run"]},
    {"role": "contributing", "slug": "contributing", "title": "Contributing", "why": "Gates.", "primary": []},
]


def chapter_reply(k, ref_path=None):
    steps = [{"text": "Start in main.", "path": ref_path, "ref": {"start": 1, "end": 5}}] if ref_path else []
    return json.dumps({"what_this_is": f"Chapter text {k}.", "diagram": "graph TD\n  a --> b", "steps": steps,
                       "changes": [], "gotchas": []})


def book_scenario(files=BOOK_FILES, plan=BOOK_PLAN, n_chapters=5, **extra):
    """Stub replies: catalog rows for every file, the plan, chapter k (call order; call 2 cites app.py), index."""
    rows = "\n".join(json.dumps({"path": p, "purpose": f"Purpose of {p}.", "symbols": []}) for p in files)
    chapters = [chapter_reply(k, "app.py" if k == 1 else None) for k in range(40)]
    index = json.dumps({"overview": "A demo.", "diagram": "graph TD\n  x --> y",
                        "why": [f"why {i}" for i in range(n_chapters)]})
    return {"catalog": rows, "plan": json.dumps(plan), "chapter": chapters, "index": index, **extra}


@pytest.fixture
def tool(rs, stub, make_repo, monkeypatch, tmp_path):
    """Runs main() against a fixture repo with the stub backend; counts stub calls per stage."""
    class Tool:
        def __init__(self):
            self.env = None

        def repo(self, files=BOOK_FILES, **kw):
            return make_repo(tmp_path, files, **kw)

        def scenario(self, scenario, **env):
            self.env = stub(scenario)
            for k, v in {**self.env, "REPO_SUMMARIZE_PASS_ENV": "STUB_SCENARIO STUB_LOG STUB_VERSION",
                         **env}.items():
                monkeypatch.setenv(k, v)

        def calls(self):
            log = Path(self.env["STUB_LOG"])
            return [json.loads(ln)["stage"] for ln in log.read_text().splitlines()] if log.exists() else []

        def run(self, repo, *args):
            before = len(self.calls())
            code = rs.main([str(repo), *args])
            return code, [s for s in self.calls()[before:] if s != "probe"]

        def no_sandbox(self):
            monkeypatch.setattr(rs, "detect_sandbox", lambda: "none")

    return Tool()

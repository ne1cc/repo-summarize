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

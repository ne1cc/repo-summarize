def graph(rs, make_repo, tmp_path, files):
    root = make_repo(tmp_path, files)
    disc = rs.discover(root)
    snap = rs.take_snapshot(disc, tmp_path / "run")
    return snap, disc.included


def build(rs, make_repo, tmp_path, files):
    snap, inc = graph(rs, make_repo, tmp_path, files)
    return rs.build_graph(snap, inc)


def test_py_relative_and_absolute(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {
        "pkg/__init__.py": "", "pkg/a.py": "from .b import x\nimport pkg.mod\n", "pkg/b.py": "x = 1\n",
        "pkg/mod.py": "y = 2\n"})
    assert g.edges == {("pkg/a.py", "pkg/b.py"), ("pkg/a.py", "pkg/mod.py")}
    assert g.fan_in["pkg/b.py"] == 1


def test_js_relative_index(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {
        "src/app.ts": "import { f } from './lib'\nimport z from '@/util'\n", "src/lib/index.ts": "export const f = 1\n",
        "src/util.ts": "export default 1\n"})
    assert g.edges == {("src/app.ts", "src/lib/index.ts"), ("src/app.ts", "src/util.ts")}


def test_ambiguous_dropped(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {"a/utils.py": "", "b/utils.py": "", "m.py": "import utils\n"})
    assert g.edges == set()


def test_shim_one_hop(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {
        "t.py": "from shim import f\nprint(f)\n", "shim.py": "# re-export\nfrom real import f\n",
        "real.py": "def f(): pass\n"})
    assert g.shims == {"shim.py"}
    assert ("t.py", "real.py") in g.edges and ("t.py", "shim.py") in g.edges
    assert g.fan_in["real.py"] == 2


def test_entry_points(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {
        "pkg/__main__.py": "", "pkg/cli.py": "", "app.py": "",
        "pyproject.toml": '[project.scripts]\nx = "pkg.cli:main"\n',
        "Dockerfile": 'FROM python\nCMD ["python","app.py"]\n', "other.py": ""})
    assert g.entry_points == ["app.py", "pkg/__main__.py", "pkg/cli.py"]


def test_entry_points_bin_and_malformed(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {
        "package.json": '{"bin": {"t": "./tools/t.js"}}', "tools/t.js": "", "Dockerfile.x": "ENTRYPOINT python tools/t.js\n"})
    assert g.entry_points == ["tools/t.js"]
    g = build(rs, make_repo, tmp_path / "m", {"package.json": "{bad", "pyproject.toml": "[[[", "x.py": ""})
    assert g.entry_points == []


def test_manifest_commands(rs, make_repo, tmp_path):
    snap, inc = graph(rs, make_repo, tmp_path, {
        "Makefile": "CC := gcc\n.PHONY: test\ntest:\n\tpytest\n",
        "package.json": '{"scripts": {"build": "tsc"}}',
        "pyproject.toml": '[project.scripts]\nx = "pkg.cli:main"\n',
        "justfile": "set shell := ['sh']\nlint arg:\n  ruff\n",
        ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: uv run pytest\n"
                                    "      - name: multi\n        run: |\n          echo a\n          echo b\n      - uses: x\n"})
    assert rs.manifest_commands(snap, inc) == [
        "make test", "npm run build", "x", "just lint", "uv run pytest", "echo a", "echo b"]


def test_unsupported_langs(rs, make_repo, tmp_path):
    g = build(rs, make_repo, tmp_path, {"a.swift": "", "b.py": "", "c.json": "{}"})
    assert g.unsupported_langs == ["swift"]


def test_import_path_len(rs):
    g = rs.Graph({("a", "b"), ("c", "b")}, set(), [], [], {})
    assert rs.import_path_len(g, "a", "b") == 1
    assert rs.import_path_len(g, "a", "c") == 2
    assert rs.import_path_len(g, "a", "z") is None
    assert rs.import_path_len(g, "a", "c", max_len=1) is None

import os


def skipped(d, reason):
    return d.skipped.get(reason, [])


def test_shebang_script_included(rs, make_repo, tmp_path):
    d = rs.discover(make_repo(tmp_path, {"bin/tool": "#!/usr/bin/env bash\necho\n", "bin/other": "plain\n"}))
    assert "bin/tool" in d.included
    assert "bin/other" in skipped(d, "unsupported-type")


def test_src_build_dir_included(rs, make_repo, tmp_path):
    assert "src/build/a.py" in rs.discover(make_repo(tmp_path, {"src/build/a.py": "x=1\n"})).included


def test_env_excluded_example_included(rs, make_repo, tmp_path):
    d = rs.discover(make_repo(tmp_path, {".env": "A=1\n", ".env.local": "A=1\n", ".env.example": "A=\n"}))
    assert ".env" in skipped(d, "secret-file") and ".env.local" in skipped(d, "secret-file")
    assert ".env.example" in d.included


def test_secret_files(rs, make_repo, tmp_path):
    files = {"id_rsa": "k", "x.pem": "k", "secrets/a.txt": "k", "my-credentials.json": "{}"}
    d = rs.discover(make_repo(tmp_path, files))
    assert sorted(skipped(d, "secret-file")) == sorted(files)


def test_binary_and_large(rs, make_repo, tmp_path):
    big = "a" * (rs.MAX_FILE + 1)
    d = rs.discover(make_repo(tmp_path, {"b.py": b"x\x00y", "big.py": big, "ok.py": "a" * rs.MAX_FILE}))
    assert skipped(d, "binary") == ["b.py"]
    assert skipped(d, "too-large") == ["big.py"]
    assert d.included == ["ok.py"]


def test_lock_and_minified(rs, make_repo, tmp_path):
    d = rs.discover(make_repo(tmp_path, {"uv.lock": "x", "a.min.js": "x", "package-lock.json": "{}"}))
    assert sorted(skipped(d, "lockfile")) == ["package-lock.json", "uv.lock"]
    assert skipped(d, "minified") == ["a.min.js"]


def test_generated_docs_skipped(rs, make_repo, tmp_path):
    d = rs.discover(make_repo(tmp_path, {"docs/architecture/x.md": "x", "docs/.repo-summarize/y": "x"}))
    assert sorted(skipped(d, "generated-docs")) == ["docs/.repo-summarize/y", "docs/architecture/x.md"]


def test_unsafe_path(rs, make_repo, tmp_path):
    d = rs.discover(make_repo(tmp_path, {"a\tb.py": "x=1\n", "a|b.py": "x=1\n"}))
    assert sorted(skipped(d, "unsafe-path")) == ["a\tb.py", "a|b.py"]


def test_symlink_skipped(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x=1\n"}, commit=False)
    os.symlink("a.py", repo / "link.py")
    assert skipped(rs.discover(repo), "symlink") == ["link.py"]


def test_config_types_included(rs, make_repo, tmp_path):
    ok = ["a.yml", "Dockerfile", "Dockerfile.dev", "Makefile", ".github/workflows/ci.yml", "README.md", ".github/PULL_REQUEST_TEMPLATE.md"]
    d = rs.discover(make_repo(tmp_path, {**dict.fromkeys(ok, "x\n"), "docs/guide.md": "x\n"}))
    assert d.included == sorted(ok)
    assert skipped(d, "unsupported-type") == ["docs/guide.md"]


def test_non_git_dir_uses_walk(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x=1\n", ".git/config": "x"}, git=False)
    d = rs.discover(repo)
    assert d.included == ["a.py"] and d.discovered == ["a.py"]


def test_untracked_included_ignored_excluded(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {".gitignore": "ign.py\n", "a.py": "x=1\n"})
    (repo / "ign.py").write_text("x=1\n")
    (repo / "new.py").write_text("x=1\n")
    d = rs.discover(repo)
    assert "new.py" in d.included and "ign.py" not in d.discovered

import hashlib
import json
import stat


def test_redact_keeps_line_count(rs):
    pem = "-----BEGIN RSA PRIVATE KEY-----\nAAAA\nBBBB\nCCCC\n-----END RSA PRIVATE KEY-----"
    text = "a\nb\n" + pem + "\nc\nd\n"
    out, n = rs.redact_text(text)
    assert len(out.splitlines()) == len(text.splitlines()) == 9
    assert out.split("\n")[2:7] == ["[REDACTED]"] * 5
    assert n >= 1


def test_redact_patterns(rs):
    for secret in ["AKIA" + "A1B2C3D4E5F6G7H8", "ghp_" + "a" * 36, "sk-" + "b" * 24, "xoxb-1-2",
                   'api_key = "abcdefgh12"']:
        out, n = rs.redact_text(f"x {secret} y")
        assert n >= 1 and secret not in out and rs.scan_secret(secret)
    out, _ = rs.redact_text('api_key = "abcdefgh12"')
    assert out.startswith("api_key = ") and "[REDACTED]" in out


def test_redact_leaves_code(rs):
    assert rs.redact_text("token_count = len(x)") == ("token_count = len(x)", 0)
    assert not rs.scan_secret("token_count = len(x)")


def test_snapshot_mode_and_hash(rs, make_repo, tmp_path):
    data = b"print(1)\nkey = 'sk-" + b"z" * 24 + b"'\n"
    d = rs.discover(make_repo(tmp_path, {"a/b.py": data}))
    s1 = rs.take_snapshot(d, tmp_path / "run1")
    s2 = rs.take_snapshot(d, tmp_path / "run2")
    f = s1.dir / "a" / "b.py"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert s1.sha256["a/b.py"] == hashlib.sha256(data).hexdigest()
    assert b"sk-" not in f.read_bytes()
    want = hashlib.sha256(json.dumps(sorted(s1.sha256.items()), separators=(",", ":")).encode()).hexdigest()
    assert s1.manifest_sha256 == s2.manifest_sha256 == want


def test_latin1_file(rs, make_repo, tmp_path):
    raw = b"x = '\xe9'\n" * 3
    d = rs.discover(make_repo(tmp_path, {"a.py": raw}))
    s = rs.take_snapshot(d, tmp_path / "run")
    assert len(rs.read_snapshot(s, "a.py")) == 3
    assert (s.dir / "a.py").read_bytes() == raw


def test_changed_since_snapshot(rs, make_repo, tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x=1\n", "b.py": "y=1\n", "c.py": "z=1\n"})
    d = rs.discover(repo)
    s = rs.take_snapshot(d, tmp_path / "run")
    assert rs.changed_since_snapshot(d, s) == []
    (repo / "a.py").write_text("x=2\n")
    (repo / "c.py").unlink()
    assert rs.changed_since_snapshot(d, s) == ["a.py", "c.py"]

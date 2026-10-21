"""Fake AI backend. Python 3.9-compatible: it may run under /usr/bin/python3."""
import json
import os
import signal
import sys
import time
from pathlib import Path


def main():
    if sys.argv[1:2] == ["--version"]:
        print(os.environ.get("STUB_VERSION", "stub-1"))
        return 0
    prompt = sys.argv[-1]
    first = prompt.split("\n", 1)[0]
    stage = first[len("STAGE:"):].strip() if first.startswith("STAGE:") else first.strip()
    scenario = json.loads(Path(os.environ["STUB_SCENARIO"]).read_text())
    log = Path(os.environ["STUB_LOG"])
    seen = 0
    if log.exists():
        seen = sum(1 for ln in log.read_text().splitlines() if json.loads(ln)["stage"] == stage)
    env = os.environ
    with log.open("a") as f:
        f.write(json.dumps({
            "stage": stage,
            "prompt_bytes": len(prompt.encode()),
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "cwd_files": sorted(os.listdir(".")),
            "env_keys": sorted(env),
            "env": {k: v for k, v in env.items()
                    if k.startswith(("FOO", "STUB_")) or k in ("PATH", "HOME")},
        }) + "\n")
    time.sleep(scenario.get("sleep", 0))
    if "mutate" in scenario:
        m = scenario["mutate"]
        Path(m["path"]).write_text(m["content"])
    staged = scenario.get("mutate_on_stage", {}).get(stage)
    if staged:
        Path(staged["path"]).write_text(staged["content"])
    if scenario.get("sigint_on_stage") == stage:
        os.kill(os.getppid(), signal.SIGINT)  # under sandbox-exec (which execs) the parent is the tool
        time.sleep(2)
    fail_after = scenario.get("fail_after", {}).get(stage)
    if fail_after is not None and seen >= fail_after:
        return 1
    if scenario.get("stderr"):
        sys.stderr.write(scenario["stderr"])
    reply = scenario.get(stage, "")
    if isinstance(reply, list):
        reply = reply[min(seen, len(reply) - 1)] if reply else ""
    if "read_path" in scenario:
        try:
            reply = Path(scenario["read_path"]).read_text()
        except OSError as e:
            reply = "read-failed: " + type(e).__name__
    for p in scenario.get("write_paths", []):
        try:
            Path(p).write_text("x")
            reply += "\nwrote " + p
        except OSError:
            reply += "\nwrite-failed " + p
    sys.stdout.write(reply)
    return scenario.get("exit_code", 0)


sys.exit(main())

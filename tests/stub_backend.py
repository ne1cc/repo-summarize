"""Fake AI backend. Python 3.9-compatible: it may run under /usr/bin/python3."""
import json
import os
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
            "env_keys": sorted(env),
            "env": {k: v for k, v in env.items()
                    if k.startswith(("FOO", "STUB_")) or k in ("PATH", "HOME")},
        }) + "\n")
    time.sleep(scenario.get("sleep", 0))
    if "mutate" in scenario:
        m = scenario["mutate"]
        Path(m["path"]).write_text(m["content"])
    if scenario.get("stderr"):
        sys.stderr.write(scenario["stderr"])
    if scenario.get("exit_code"):
        return scenario["exit_code"]
    reply = scenario.get(stage, "")
    if isinstance(reply, list):
        reply = reply[min(seen, len(reply) - 1)] if reply else ""
    sys.stdout.write(reply)
    return 0


sys.exit(main())

"""Shared helpers for the fix and review agents: subprocess calls, git worktrees, the test runner, the
"red check", headless Claude Code calls and the JSONL run log."""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "runs"
WORKTREES = REPO / ".worktrees"

# Unit tests run with the standard library; set PIPELINE_TEST_CMD (e.g. "python -m pytest -q") to use another runner.
TEST_CMD = os.environ.get("PIPELINE_TEST_CMD", "python -m unittest discover -s tests -t . -v").split()
CLAUDE = os.environ.get("CLAUDE_BIN", "claude")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub(text: str, *roots: Path) -> str:
    """Remove machine-specific paths from text that goes into logs, PR bodies and comments."""
    for root, label in [(r, "<worktree>") for r in roots] + [(REPO, "<repo>"), (Path.home(), "~")]:
        for form in {str(root), str(root).replace("\\", "/"), str(root).replace("\\", "\\\\")}:
            text = text.replace(form, label)
    text = text.replace(sys.executable, "python")
    return re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "~", text)


def run(cmd: list[str], cwd: Path, env: dict | None = None, timeout: int = 600, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def git(cwd: Path, *args: str) -> str:
    p = run(["git", *args], cwd)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


class RunLog:
    """One JSON object per line in runs/<run_id>.jsonl; artifacts in runs/<run_id>/."""

    def __init__(self, kind: str, slug: str):
        self.run_id = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}-{kind}-{slug}"
        RUNS.mkdir(exist_ok=True)
        self.path = RUNS / f"{self.run_id}.jsonl"
        self.dir = RUNS / self.run_id
        self.dir.mkdir()
        self.t0 = time.monotonic()

    def event(self, event: str, **fields) -> None:
        rec = {"time": now(), "run_id": self.run_id, "event": event, "elapsed_s": round(time.monotonic() - self.t0, 1), **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def artifact(self, name: str, text: str) -> str:
        (self.dir / name).write_text(text, encoding="utf-8")
        return f"runs/{self.run_id}/{name}"


def add_worktree(name: str, ref: str, branch: str | None = None) -> Path:
    WORKTREES.mkdir(exist_ok=True)
    path = WORKTREES / name
    if branch:
        git(REPO, "worktree", "add", "-b", branch, str(path), ref)
    else:
        git(REPO, "worktree", "add", "--detach", str(path), ref)
    return path


def remove_worktree(path: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(path)], REPO)
    shutil.rmtree(path, ignore_errors=True)


def run_tests(cwd: Path, files: list[str] | None = None) -> dict:
    """Run the suite (or some test files) and summarise: passed, counts, the output's tail."""
    cmd = [sys.executable if c == "python" else c for c in TEST_CMD]
    if files:
        if "pytest" in cmd:
            cmd = cmd + files
        else:
            cmd = [c for c in cmd if c not in ("discover", "-s", "tests", "-t", ".")] + [module_of(f) for f in files]
    t = time.monotonic()
    p = run(cmd, cwd, timeout=600)
    out = scrub(p.stdout + p.stderr, cwd)
    ran = re.search(r"Ran (\d+) tests?", out)
    fail = re.search(r"FAILED \(([^)]*)\)", out)
    return {"passed": p.returncode == 0, "exit_code": p.returncode, "tests_run": int(ran.group(1)) if ran else None,
            "failures": fail.group(1) if fail else "", "seconds": round(time.monotonic() - t, 2), "output": out}


def module_of(test_file: str) -> str:
    return test_file[:-3].replace("/", ".")


def red_check(cwd: Path, base: str, changed: list[str]) -> dict:
    """Do the changed tests catch the bug? Put the base version of every changed non-test file back, run only the changed
    test modules (they must FAIL), then restore the fixed files."""
    tests = [f for f in changed if f.startswith("tests/") and f.endswith(".py") and Path(f).name.startswith("test_")]
    src = [f for f in changed if f not in tests and not f.startswith("tests/")]
    if not tests:
        return {"done": False, "reason": "no test file changed", "tests": [], "reverted": src}
    saved = {f: (cwd / f).read_bytes() if (cwd / f).exists() else None for f in src}
    try:
        for f in src:
            old = run(["git", "show", f"{base}:{f}"], cwd)
            if old.returncode == 0:
                (cwd / f).write_text(old.stdout, encoding="utf-8", newline="")
            elif (cwd / f).exists():
                (cwd / f).unlink()                       # the file is new in the change
        res = run_tests(cwd, tests)
    finally:
        for f, data in saved.items():
            if data is None:
                (cwd / f).unlink(missing_ok=True)
            else:
                (cwd / f).write_bytes(data)
    return {"done": True, "tests": tests, "reverted": src, "fails_without_fix": not res["passed"], "result": res}


KEEP = {"ANTHROPIC_API_KEY", "CLAUDE_CODE_GIT_BASH_PATH"}


def claude_env() -> dict:
    """The agent's environment: no GitHub or other tokens, and nothing inherited from a Claude Code session that may have
    started this script (its session, socket and mode variables); only what the agent's own Claude Code needs."""
    drop = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|_KEY)$|^(CLAUDE|ANTHROPIC)", re.I)
    return {k: v for k, v in os.environ.items() if k in KEEP or not drop.search(k)}


def run_claude(prompt: str, cwd: Path, allowed: list[str], disallowed: list[str], model: str | None = None,
               timeout: int = 1200) -> dict:
    """One headless Claude Code session (`claude -p`), prompt on stdin, JSON result. In CI (ANTHROPIC_API_KEY set) --bare
    skips hooks, plugins and CLAUDE.md discovery; locally the user's login is used, user settings and MCP servers are not."""
    cmd = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "dontAsk", "--no-session-persistence",
           "--strict-mcp-config", "--setting-sources", "project", "--allowedTools", *allowed, "--disallowedTools", *disallowed]
    if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("PIPELINE_BARE", "1") == "1":
        cmd.insert(2, "--bare")
    if model:
        cmd += ["--model", model]
    t = time.monotonic()
    p = run(cmd, cwd, env=claude_env(), timeout=timeout, stdin=prompt)
    out = {"exit_code": p.returncode, "seconds": round(time.monotonic() - t, 1), "stderr": scrub(p.stderr[-2000:], cwd)}
    try:
        res = json.loads(p.stdout)
        out.update({k: res.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms", "total_cost_usd")})
        out["result"] = scrub(res.get("result") or "", cwd)
    except json.JSONDecodeError:
        out["result"] = scrub(p.stdout[-4000:], cwd)
    return out


def gh_available() -> bool:
    if shutil.which("gh") is None:
        return False
    return run(["gh", "auth", "status"], REPO, timeout=60).returncode == 0


def excerpt(text: str, lines: int = 25) -> str:
    rows = text.strip().splitlines()
    return "\n".join(rows[-lines:])

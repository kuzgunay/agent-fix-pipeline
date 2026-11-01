"""Fix agent: a bug report (or a failing test) in, a pull request with evidence out.

    python pipeline/fix_agent.py --issue issues/001-split-loses-a-cent.md
    python pipeline/fix_agent.py --github-issue 12          # the report is a GitHub issue (needs gh)
    python pipeline/fix_agent.py --failing-test tests/test_split.py

1. A new branch in its own git worktree under .worktrees/ (the sandbox: the agent never touches the main checkout).
2. The suite runs on the base: "before".
3. A headless Claude Code session (`claude -p`) works in that worktree with a fixed tool list: Read, Edit, Write, Glob,
   Grep, and Bash for the test runner and read-only git only. No web tools, no MCP servers, no tokens in its environment.
   Its instructions: reproduce the bug with a failing test first, then fix it, change nothing else.
4. The pipeline (not the agent) checks the result: the suite passes ("after"), and the new tests FAIL when the fix is
   taken back out ("red check"). No PR unless both hold.
5. The pipeline commits, pushes the branch and opens a PR whose body carries the evidence (gh). Without a working gh it
   writes the PR body and the exact gh command into runs/<run_id>/ for a person to run.
Every step is a line in runs/<run_id>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (REPO, RunLog, add_worktree, excerpt, gh_available, git, red_check, remove_worktree, run, run_claude,
                    run_tests, scrub)

ALLOWED = ["Read", "Edit", "Write", "Glob", "Grep",
           "Bash(python -m unittest:*)", "Bash(python -m pytest:*)", "Bash(git diff:*)", "Bash(git status:*)"]
DISALLOWED = ["WebFetch", "WebSearch", "NotebookEdit", "Bash(git push:*)", "Bash(git commit:*)", "Bash(gh:*)", "Bash(curl:*)"]

PROMPT = """You are a careful maintainer fixing one bug in this Python repository (package `ledger`, tests in `tests/`,
standard-library unittest; run them with `python -m unittest discover -s tests -t . -v`).

{trigger}

Work in this order:
1. Read the relevant code and tests.
2. Write a NEW test that reproduces the reported bug. Put it in the matching tests/test_*.py file. Run the tests and
   confirm the new test fails for the reason in the report.
3. Fix the code with the smallest change that makes the new test pass. Do not weaken or delete existing tests and do not
   edit unrelated files.
4. Run the whole suite and confirm it passes.

You cannot commit, push or use the network; the pipeline does that after checking your work. End with a short plain-text
summary: the root cause, the fix, and the test you added."""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--issue", help="a bug report file, e.g. issues/001-...md")
    g.add_argument("--github-issue", type=int, help="a GitHub issue number (read with gh)")
    g.add_argument("--failing-test", help="a test file that fails on the base branch")
    ap.add_argument("--base", default="main")
    ap.add_argument("--model")
    ap.add_argument("--no-pr", action="store_true", help="stop after the checks; do not push or open a PR")
    ap.add_argument("--keep", action="store_true", help="keep the worktree")
    a = ap.parse_args()

    if a.issue:
        report = (REPO / a.issue).read_text(encoding="utf-8"); source = a.issue
        title = report.splitlines()[0].lstrip("# ").strip()
        trigger = f"Bug report ({a.issue}):\n\n{report}"
    elif a.github_issue:
        data = json.loads(run(["gh", "issue", "view", str(a.github_issue), "--json", "title,body"], REPO).stdout)
        title, report, source = data["title"], data["body"], f"#{a.github_issue}"
        trigger = f"Bug report (GitHub issue #{a.github_issue}): {title}\n\n{report}"
    else:
        title, source = f"Failing test {a.failing_test}", a.failing_test
        report = f"The test file {a.failing_test} fails on {a.base}."
        trigger = (f"A test fails on the base branch: {a.failing_test}. Find out why. If the test is right, fix the code (step 2 "
                   f"is then already done: the failing test is the reproduction). If the test itself is wrong, say so and change nothing.")

    log = RunLog("fix", slugify(title)); branch = f"agent/fix-{slugify(title)}-{log.run_id[:13].lower()}"
    base_sha = git(REPO, "rev-parse", a.base).strip()
    log.event("start", trigger=source, title=title, base=a.base, base_sha=base_sha, branch=branch, allowed_tools=ALLOWED,
              disallowed_tools=DISALLOWED)
    wt = add_worktree(log.run_id, a.base, branch)
    try:
        before = run_tests(wt); log.artifact("tests_before.txt", before["output"])
        log.event("tests_before", **{k: v for k, v in before.items() if k != "output"})

        agent = run_claude(PROMPT.format(trigger=trigger), wt, ALLOWED, DISALLOWED, a.model)
        log.artifact("agent_result.txt", agent["result"])
        log.event("agent", **{k: v for k, v in agent.items() if k != "result"})

        git(wt, "add", "-A")
        changed = [f for f in git(wt, "diff", "--cached", "--name-only", base_sha).split() if f]
        stat = scrub(git(wt, "diff", "--cached", "--stat", base_sha), wt)
        after = run_tests(wt); log.artifact("tests_after.txt", after["output"])
        red = red_check(wt, base_sha, changed)
        if red.get("done"):
            log.artifact("red_check.txt", red["result"]["output"])
        log.event("checks", changed=changed, diff_stat=stat.strip().splitlines()[-1:] or [""],
                  tests_after={k: v for k, v in after.items() if k != "output"},
                  red_check={k: v for k, v in red.items() if k != "result"})

        ok = agent["exit_code"] == 0 and after["passed"] and red.get("fails_without_fix") is True
        if not ok:
            reason = (f"agent failed: {agent['result'].strip()[:160]}" if agent["exit_code"] else "suite fails after the change" if not after["passed"]
                      else red.get("reason") or "the new tests pass without the fix")
            log.event("end", outcome="no_pr", reason=reason, exit_code=1)
            print(f"no PR: {reason}; log runs/{log.run_id}.jsonl")
            return 1

        msg = (f"Fix: {title}\n\nOpened by the fix agent (headless Claude Code) from {source}.\n"
               f"Run log: runs/{log.run_id}.jsonl\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
        git(wt, "commit", "-q", "-m", msg); head = git(wt, "rev-parse", "HEAD").strip()
        body = pr_body(title, source, report, agent, stat, before, red, after, log.run_id, base_sha)
        body_path = log.artifact("pr_body.md", body)
        log.event("commit", head_sha=head)
        if a.no_pr:
            log.event("end", outcome="checked_no_pr", exit_code=0); print(f"checked, no PR (--no-pr); {body_path}")
            return 0

        push = run(["git", "push", "-u", "origin", branch], wt, timeout=300)
        log.event("push", exit_code=push.returncode, stderr=scrub(push.stderr[-500:], wt))
        if push.returncode != 0:
            log.event("end", outcome="push_failed", exit_code=1); return 1
        pr_title = f"[fix-agent] {title}"
        if gh_available():
            p = run(["gh", "pr", "create", "--base", a.base, "--head", branch, "--title", pr_title, "--body-file",
                     str(REPO / body_path)], REPO, timeout=120)
            url = p.stdout.strip()
            log.event("pr", url=url, exit_code=p.returncode, opened_by="pipeline (gh)")
        else:
            cmd = f'gh pr create --base {a.base} --head {branch} --title "{pr_title}" --body-file {body_path}'
            log.artifact("open_pr.sh", cmd + "\n")
            log.event("pr", url=None, opened_by="not opened: gh unavailable here; command left for a person", command=cmd)
            print("gh unavailable; to open the PR run:\n  " + cmd)
        log.event("end", outcome="pr", exit_code=0)
        return 0
    finally:
        if not a.keep:
            remove_worktree(wt)


def pr_body(title, source, report, agent, stat, before, red, after, run_id, base_sha) -> str:
    quoted = "\n".join("> " + r for r in report.strip().splitlines())
    rr = red["result"]
    return f"""**Opened by the fix agent**: a headless Claude Code session (`claude -p`) in a sandboxed git worktree, started by
`pipeline/fix_agent.py` from `{source}`. A person reviews and merges; the review agent comments separately.

## Report
{quoted}

## Agent's summary
{agent['result'].strip()}

## Change
```
{stat.strip()}
```

## Evidence
| Check | Result |
|---|---|
| Suite on the base (`{base_sha[:7]}`) | {'pass' if before['passed'] else 'FAIL'}, {before['tests_run']} tests |
| New tests with the fix taken out (red check) | {'FAIL, as it should' if red['fails_without_fix'] else 'pass: the test does not catch the bug'} ({', '.join(red['tests'])}) |
| Suite with the fix | {'pass' if after['passed'] else 'FAIL'}, {after['tests_run']} tests |

<details><summary>Red check output (fix taken out)</summary>

```
{excerpt(rr['output'], 30)}
```
</details>

<details><summary>Suite output with the fix</summary>

```
{excerpt(after['output'], 30)}
```
</details>

## Agent run
- Tools: Read, Edit, Write, Glob, Grep; Bash only for the test runner, `git diff` and `git status`. No web, no MCP, no tokens.
- {agent.get('num_turns')} turns, {agent['seconds']} s{f", ${agent['total_cost_usd']:.2f}" if agent.get('total_cost_usd') else ''}.
- Log: `runs/{run_id}.jsonl`
"""


if __name__ == "__main__":
    sys.exit(main())

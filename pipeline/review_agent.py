"""Review agent: a second, separate Claude Code session that may only read. The author never grades its own work.

    python pipeline/review_agent.py --pr 1                 # read the PR with gh, comment with gh
    python pipeline/review_agent.py --branch agent/fix-... --issue issues/001-...md   # without gh: the comment goes to a file

1. The PR's head is checked out in its own worktree (detached).
2. The pipeline runs two mechanical checks itself: the suite passes on the head, and the tests the PR adds or changes FAIL
   when the PR's code changes are reverted (the test really catches the bug; a test that passes either way proves nothing).
3. A fresh `claude -p` session gets the report, the diff and those results, with read-only tools (Read, Glob, Grep). It
   answers with a verdict (APPROVE or REQUEST_CHANGES) and its reasons.
4. The pipeline posts that as a PR comment (gh), or writes it to runs/<run_id>/review_comment.md with the gh command.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, RunLog, add_worktree, excerpt, gh_available, git, red_check, remove_worktree, run, run_claude, run_tests, scrub

ALLOWED = ["Read", "Glob", "Grep"]
DISALLOWED = ["Edit", "Write", "NotebookEdit", "Bash", "WebFetch", "WebSearch"]

PROMPT = """You are reviewing a pull request opened by another agent. You may only read files; you cannot run anything.
The repository is checked out at the PR's head in the current directory.

Bug report:
{report}

Diff against the base:
```diff
{diff}
```

Mechanical checks the pipeline already ran (you can trust these numbers):
- Suite on the PR head: {suite}
- Red check: with the PR's code changes reverted, the changed test files {red}

Review the change. Answer these, briefly and concretely:
1. Does the new test reproduce the bug described in the report (not a neighbouring behaviour)?
2. Is the fix correct and minimal? Think of edge cases the report implies; read the code to check them.
3. Were existing tests weakened, or unrelated files changed?
Start your answer with exactly one line: "Verdict: APPROVE" or "Verdict: REQUEST_CHANGES". Then the reasons, then any
follow-up worth a separate issue. Plain markdown, under 250 words."""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, help="the PR number (gh)")
    ap.add_argument("--branch", help="the PR's head branch (without gh)")
    ap.add_argument("--issue", help="the bug report file (without gh)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--model")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if not (a.pr or a.branch):
        ap.error("give --pr or --branch")

    gh = gh_available()
    if a.pr and gh:
        meta = json.loads(run(["gh", "pr", "view", str(a.pr), "--json", "headRefName,baseRefName,title,body"], REPO).stdout)
        branch, base, report = meta["headRefName"], meta["baseRefName"], meta["body"]
        m = re.search(r"## Report\n(.*?)\n## ", report, re.S)
        report = m.group(1).strip() if m else report
    else:
        branch, base = a.branch, a.base
        report = (REPO / a.issue).read_text(encoding="utf-8") if a.issue else "(no report given)"

    log = RunLog("review", re.sub(r"[^a-z0-9]+", "-", branch.lower())[:40].strip("-"))
    run(["git", "fetch", "origin", branch], REPO, timeout=300)
    ref = f"origin/{branch}" if run(["git", "rev-parse", "--verify", f"origin/{branch}"], REPO).returncode == 0 else branch
    head = git(REPO, "rev-parse", ref).strip(); merge_base = git(REPO, "merge-base", base, head).strip()
    log.event("start", pr=a.pr, branch=branch, head_sha=head, base=base, merge_base=merge_base, allowed_tools=ALLOWED,
              disallowed_tools=DISALLOWED)
    wt = add_worktree(log.run_id, head)
    try:
        changed = [f for f in git(wt, "diff", "--name-only", merge_base, "HEAD").split() if f]
        diff = scrub(git(wt, "diff", merge_base, "HEAD"), wt)
        suite = run_tests(wt); red = red_check(wt, merge_base, changed)
        log.artifact("review_suite.txt", suite["output"])
        if red.get("done"):
            log.artifact("review_red_check.txt", red["result"]["output"])
        log.event("checks", changed=changed, suite={k: v for k, v in suite.items() if k != "output"},
                  red_check={k: v for k, v in red.items() if k != "result"})
        suite_s = f"{'pass' if suite['passed'] else 'FAIL'} ({suite['tests_run']} tests)"
        red_s = ("FAIL, so they catch the bug" if red.get("fails_without_fix") else
                 "still PASS, so they do not catch the bug" if red.get("done") else f"could not be checked: {red.get('reason')}")

        rev = run_claude(PROMPT.format(report=report.strip(), diff=diff[:20000], suite=suite_s, red=red_s), wt, ALLOWED, DISALLOWED, a.model)
        log.event("agent", **{k: v for k, v in rev.items() if k != "result"})
        verdict = re.search(r"Verdict:\s*(APPROVE|REQUEST_CHANGES)", rev["result"])
        mech_ok = suite["passed"] and red.get("fails_without_fix") is True
        comment = f"""**Review agent**: a separate, read-only Claude Code session (`claude -p` with Read, Glob, Grep only),
started by `pipeline/review_agent.py`. It did not write this change.

**Mechanical checks (run by the pipeline)**
- Suite on the PR head `{head[:7]}`: {suite_s}
- Red check, PR code changes reverted: the changed tests {red_s}

<details><summary>Red check output</summary>

```
{excerpt(red['result']['output'], 25) if red.get('done') else red.get('reason')}
```
</details>

**Model review**

{rev['result'].strip()}

---
Run log: `runs/{log.run_id}.jsonl`. {'Both mechanical checks hold.' if mech_ok else 'A mechanical check failed: do not merge as is.'}
"""
        path = log.artifact("review_comment.md", comment)
        log.event("verdict", verdict=verdict.group(1) if verdict else None, mechanical_ok=mech_ok)
        if a.pr and gh:
            p = run(["gh", "pr", "comment", str(a.pr), "--body-file", str(REPO / path)], REPO, timeout=120)
            log.event("comment", posted=p.returncode == 0, by="pipeline (gh)", url=p.stdout.strip())
        else:
            cmd = f"gh pr comment {a.pr or '<PR>'} --body-file {path}"
            log.artifact("post_comment.sh", cmd + "\n")
            log.event("comment", posted=False, by="not posted: gh unavailable here; command left for a person", command=cmd)
            print("gh unavailable; to post the review run:\n  " + cmd)
        log.event("end", exit_code=0 if verdict else 1)
        return 0 if verdict else 1
    finally:
        if not a.keep:
            remove_worktree(wt)


if __name__ == "__main__":
    sys.exit(main())

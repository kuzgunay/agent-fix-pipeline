**Review agent**: a separate, read-only Claude Code session (`claude -p` with Read, Glob, Grep only),
started by `pipeline/review_agent.py`. It did not write this change.

**Mechanical checks (run by the pipeline)**
- Suite on the PR head `6a5c8bc`: pass (12 tests)
- Red check, PR code changes reverted: the changed tests FAIL, so they catch the bug

<details><summary>Red check output</summary>

```
test_divides_exactly (tests.test_split.SplitEvenlyTest.test_divides_exactly) ... ok
test_one_person (tests.test_split.SplitEvenlyTest.test_one_person) ... ok
test_rejects_no_people (tests.test_split.SplitEvenlyTest.test_rejects_no_people) ... ok
test_remainder_is_not_lost (tests.test_split.SplitEvenlyTest.test_remainder_is_not_lost) ... FAIL

======================================================================
FAIL: test_remainder_is_not_lost (tests.test_split.SplitEvenlyTest.test_remainder_is_not_lost)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<worktree>\tests\test_split.py", line 13, in test_remainder_is_not_lost
    self.assertEqual(sum(shares), 1000)
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
AssertionError: 999 != 1000

----------------------------------------------------------------------
Ran 4 tests in 0.001s

FAILED (failures=1)
```
</details>

**Model review**

Verdict: APPROVE

**1. Does the test reproduce the bug?** Yes. `test_remainder_is_not_lost` uses the exact case from the report, 1000 cents split 3 ways. It checks the property the report asks for: the shares add up to the bill. The red check failed with `999 != 1000`, which is the lost cent. It also checks the length and that shares differ by at most one cent, which matches the docstring. It does not pin which person pays the extra cent. That's reasonable, because the report only says "somebody pays".

**2. Is the fix correct and minimal?** Yes. With `divmod`, the first `remainder` people get one extra cent, so the shares always add up to the total and differ by at most one. I traced the edge cases by reading the code:
- **Even split** (900 / 3): remainder is 0, so the result is unchanged and `test_divides_exactly` still holds.
- **One person:** remainder is 0, so the result is `[total]`.
- **More people than cents** (2 / 3): gives `[1, 1, 0]`. That's correct.
- **Zero total:** gives all zeros.
- **Negative total** (a refund, -1000 / 3): Python's `divmod` gives (-334, 2), so the result is `[-333, -333, -334]`. It adds up and differs by one.
- **`people <= 0`:** the guard is unchanged.

The change is two lines, and `split_evenly` has no other callers in `ledger/`.

**3. Were existing tests weakened or unrelated files changed?** No. Only `ledger/split.py` and `tests/test_split.py` changed, and the test change is purely additive.

**Follow-ups (separate issues):**
- If the screen should decide who pays the extra cent (for example, the person who paid the bill), make that an explicit parameter instead of relying on list order.
- Nothing tests negative totals or more people than cents. A small property-style test would lock those in.

---
Run log: `runs/20261101T105909Z-review-agent-fix-split-bill-loses-a-cent-202611.jsonl`. Both mechanical checks hold.

**Opened by the fix agent**: a headless Claude Code session (`claude -p`) in a sandboxed git worktree, started by
`pipeline/fix_agent.py` from `issues/001-split-loses-a-cent.md`. A person reviews and merges; the review agent comments separately.

## Report
> # Split bill loses a cent
> 
> Reported from the "split bill" screen.
> 
> Splitting 10.00 between 3 people shows 3.33, 3.33 and 3.33. That adds up to 9.99, so one cent is gone. It looks fine when the amount divides evenly (9.00 / 3 is ok).
> 
> Expected: the shares add up to the bill. Somebody pays the extra cent.

## Agent's summary
The bug is fixed and all 12 tests in the suite now pass.

Root cause: `split_evenly` in `ledger/split.py` worked out each share with floor division (`total_cents // people`) and threw away the remainder. So 1000 cents split 3 ways gave three shares of 333, which add up to 999. Amounts that divide evenly, like 900 / 3, have no remainder, which is why they looked fine.

Fix: the function now uses `divmod(total_cents, people)` and gives one extra cent to the first `remainder` people. The shares always add up to the total and never differ by more than one cent, which is what the function's docstring already promised. Splitting 10.00 between 3 now gives 3.34, 3.33 and 3.33.

Test added: `test_remainder_is_not_lost` in `tests/test_split.py`. It splits 1000 cents between 3 people and checks there are 3 shares, that they add up to 1000, and that the largest and smallest differ by at most 1. Before the fix it failed with `999 != 1000`, the lost cent from the report.

The only files changed are `ledger/split.py` and `tests/test_split.py`. No existing tests were modified.

## Change
```
ledger/split.py     | 4 ++--
 tests/test_split.py | 6 ++++++
 2 files changed, 8 insertions(+), 2 deletions(-)
```

## Evidence
| Check | Result |
|---|---|
| Suite on the base (`8a71ec3`) | pass, 11 tests |
| New tests with the fix taken out (red check) | FAIL, as it should (tests/test_split.py) |
| Suite with the fix | pass, 12 tests |

<details><summary>Red check output (fix taken out)</summary>

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

<details><summary>Suite output with the fix</summary>

```
test_clamps_to_month_end (tests.test_dates.AddMonthsTest.test_clamps_to_month_end) ... ok
test_crosses_year (tests.test_dates.AddMonthsTest.test_crosses_year) ... ok
test_february (tests.test_dates.DaysInMonthTest.test_february) ... ok
test_thirty_day_months (tests.test_dates.DaysInMonthTest.test_thirty_day_months) ... ok
test_total_and_due_date (tests.test_invoice.InvoiceTest.test_total_and_due_date) ... ok
test_format (tests.test_money.FormatCentsTest.test_format) ... ok
test_surrounding_spaces (tests.test_money.ToCentsTest.test_surrounding_spaces) ... ok
test_whole_and_half_amounts (tests.test_money.ToCentsTest.test_whole_and_half_amounts) ... ok
test_divides_exactly (tests.test_split.SplitEvenlyTest.test_divides_exactly) ... ok
test_one_person (tests.test_split.SplitEvenlyTest.test_one_person) ... ok
test_rejects_no_people (tests.test_split.SplitEvenlyTest.test_rejects_no_people) ... ok
test_remainder_is_not_lost (tests.test_split.SplitEvenlyTest.test_remainder_is_not_lost) ... ok

----------------------------------------------------------------------
Ran 12 tests in 0.001s

OK
```
</details>

## Agent run
- Tools: Read, Edit, Write, Glob, Grep; Bash only for the test runner, `git diff` and `git status`. No web, no MCP, no tokens.
- 7 turns, 36.0 s, $0.12.
- Log: `runs/20261101T105817Z-fix-split-bill-loses-a-cent.jsonl`

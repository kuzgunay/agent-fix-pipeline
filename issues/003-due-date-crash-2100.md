# Invoice for 31 Jan 2100 crashes

Creating an invoice issued on 2100-01-31 with one month of terms crashes when we show the due date:

    ValueError: day 29 must be in range 1..28 for month 2 in year 2100

Other years work (2024-01-31 gives 2024-02-29). Low priority but it is a crash.

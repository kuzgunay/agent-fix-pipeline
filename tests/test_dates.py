import datetime
import unittest

from ledger.dates import add_months, days_in_month


class DaysInMonthTest(unittest.TestCase):
    def test_february(self):
        self.assertEqual(days_in_month(2024, 2), 29)
        self.assertEqual(days_in_month(2023, 2), 28)

    def test_thirty_day_months(self):
        self.assertEqual(days_in_month(2023, 4), 30)


class AddMonthsTest(unittest.TestCase):
    def test_clamps_to_month_end(self):
        self.assertEqual(add_months(datetime.date(2024, 1, 31), 1), datetime.date(2024, 2, 29))

    def test_crosses_year(self):
        self.assertEqual(add_months(datetime.date(2024, 11, 15), 2), datetime.date(2025, 1, 15))


if __name__ == "__main__":
    unittest.main()

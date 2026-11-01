import datetime
import unittest

from ledger.invoice import Invoice, Line


class InvoiceTest(unittest.TestCase):
    def test_total_and_due_date(self):
        inv = Invoice(issued=datetime.date(2024, 3, 10), lines=[Line("Widget", "12.50", 2), Line("Setup", "40")])
        self.assertEqual(inv.total_cents, 6500)
        self.assertEqual(inv.due, datetime.date(2024, 4, 10))
        self.assertEqual(inv.summary(), "Total 65.00, due 2024-04-10")


if __name__ == "__main__":
    unittest.main()

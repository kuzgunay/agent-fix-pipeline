import unittest

from ledger.money import format_cents, to_cents


class ToCentsTest(unittest.TestCase):
    def test_whole_and_half_amounts(self):
        self.assertEqual(to_cents("12.50"), 1250)
        self.assertEqual(to_cents("7"), 700)

    def test_surrounding_spaces(self):
        self.assertEqual(to_cents(" 3.25 "), 325)


class FormatCentsTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_cents(1250), "12.50")
        self.assertEqual(format_cents(5), "0.05")
        self.assertEqual(format_cents(-5), "-0.05")


if __name__ == "__main__":
    unittest.main()

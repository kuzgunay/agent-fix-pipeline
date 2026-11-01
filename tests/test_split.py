import unittest

from ledger.split import split_evenly


class SplitEvenlyTest(unittest.TestCase):
    def test_divides_exactly(self):
        self.assertEqual(split_evenly(900, 3), [300, 300, 300])

    def test_remainder_is_not_lost(self):
        shares = split_evenly(1000, 3)
        self.assertEqual(len(shares), 3)
        self.assertEqual(sum(shares), 1000)
        self.assertLessEqual(max(shares) - min(shares), 1)

    def test_one_person(self):
        self.assertEqual(split_evenly(1234, 1), [1234])

    def test_rejects_no_people(self):
        with self.assertRaises(ValueError):
            split_evenly(100, 0)


if __name__ == "__main__":
    unittest.main()

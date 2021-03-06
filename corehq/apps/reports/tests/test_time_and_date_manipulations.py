from django.test import TestCase
from corehq.apps.reports.views import calculate_hour, recalculate_hour, calculate_day


class TimeAndDateManipulationTest(TestCase):
    def calculate_hour_test(self):
        self.assertEqual(calculate_hour(10, 2, 0), (12, 0))
        self.assertEqual(calculate_hour(10, -2, 0), (8, 0))
        self.assertEqual(calculate_hour(10, 2, 30), (12, 0))
        self.assertEqual(calculate_hour(10, -2, 30), (7, 0))
        self.assertEqual(calculate_hour(3, -5, 0), (22, -1))
        self.assertEqual(calculate_hour(22, 5, 0), (3, 1))
        self.assertRaises(AssertionError, calculate_hour(25, 0, 0))

    def recalculate_hour_test(self):
        self.assertEqual(recalculate_hour(12, 2, 0), (10, 0))
        self.assertEqual(recalculate_hour(8, -2, 0), (10, 0))
        self.assertEqual(recalculate_hour(12, 2, 30), (10, 0))
        self.assertEqual(recalculate_hour(7, -2, 30), (10, 0))
        self.assertEqual(recalculate_hour(22, -5, 0), (3, 1))
        self.assertEqual(recalculate_hour(3, 5, 0), (22, -1))

    def calculate_day_test(self):
        self.assertEqual(calculate_day('weekly', 1, 0), 1)
        self.assertEqual(calculate_day('monthly', 1, 0), 1)
        self.assertEqual(calculate_day('weekly', 6, -1), 5)
        self.assertEqual(calculate_day('monthly', 6, -1), 5)
        self.assertEqual(calculate_day('monthly', 5, 1), 6)
        self.assertEqual(calculate_day('monthly', 5, 1), 6)
        self.assertEqual(calculate_day('weekly', 1, -1), 6)
        self.assertEqual(calculate_day('monthly', 1, -1), 31)
        self.assertEqual(calculate_day('weekly', 6, 1), 0)
        self.assertEqual(calculate_day('monthly', 31, 1), 1)



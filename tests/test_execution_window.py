from datetime import datetime
import unittest

from app.database import calculate_next_expected


def window_job(interval=30):
    return {
        "schedule_cron": None,
        "expected_interval_minutes": interval,
        "execution_window_start": "07:00",
        "execution_window_end": "18:00",
        "execution_weekdays": "1,2,3,4,5,6,7",
    }


class ExecutionWindowTests(unittest.TestCase):
    def test_before_window_uses_today_start(self):
        self.assertEqual(
            calculate_next_expected(window_job(), datetime(2026, 9, 15, 6, 45)),
            datetime(2026, 9, 15, 7, 0),
        )

    def test_last_interval_does_not_cross_exclusive_end(self):
        self.assertEqual(
            calculate_next_expected(window_job(), datetime(2026, 9, 15, 17, 35)),
            datetime(2026, 9, 16, 7, 0),
        )

    def test_at_or_after_window_end_skips_to_next_day(self):
        for base in (datetime(2026, 9, 15, 18, 0), datetime(2026, 9, 15, 18, 1)):
            with self.subTest(base=base):
                self.assertEqual(
                    calculate_next_expected(window_job(), base),
                    datetime(2026, 9, 16, 7, 0),
                )

    def test_end_of_window_is_exclusive(self):
        self.assertEqual(
            calculate_next_expected(window_job(), datetime(2026, 9, 15, 17, 59)),
            datetime(2026, 9, 16, 7, 0),
        )

    def test_weekend_skips_to_monday(self):
        job = window_job(60)
        job["execution_weekdays"] = "1,2,3,4,5"
        self.assertEqual(
            calculate_next_expected(job, datetime(2026, 9, 18, 17, 30)),
            datetime(2026, 9, 21, 7, 0),
        )

    def test_windows_scheduler_example(self):
        job = window_job(60)
        job.update({
            "execution_window_start": "09:00",
            "execution_window_end": "12:00",
            "execution_weekdays": "1,2,3,4,5",
        })
        self.assertEqual(calculate_next_expected(job, datetime(2026, 9, 15, 9, 5)), datetime(2026, 9, 15, 10, 0))
        self.assertEqual(calculate_next_expected(job, datetime(2026, 9, 15, 11, 5)), datetime(2026, 9, 16, 9, 0))

    def test_without_window_preserves_continuous_interval(self):
        job = {"schedule_cron": None, "expected_interval_minutes": 30}
        self.assertEqual(
            calculate_next_expected(job, datetime(2026, 9, 15, 18, 1)),
            datetime(2026, 9, 15, 18, 31),
        )


if __name__ == "__main__":
    unittest.main()

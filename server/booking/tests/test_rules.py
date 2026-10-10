from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from booking import rules

TZ = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 12)


def at(h, m=0, day=DAY):
    return datetime.combine(day, time(h, m), TZ)


def cafe(opens=time(10), closes=time(23), step=30):
    return SimpleNamespace(booking_step_min=step, min_booking_min=60, advance_days=7, opens_at=opens, closes_at=closes)


NORMAL, LATE, ALWAYS = cafe(), cafe(closes=time(2)), cafe(opens=time(0), closes=time(0))
NOW = at(9)


class PriceTests(SimpleTestCase):
    def test_price(self):
        self.assertEqual(rules.price_paise(100, 90), 15000)
        self.assertEqual(rules.price_paise(99, 15), 2475)
        self.assertEqual(rules.price_paise(100, 60), 10000)


class OpeningPeriodTests(SimpleTestCase):
    def test_normal_day(self):
        self.assertEqual(rules.opening_period(at(12), time(10), time(23)), (at(10), at(23)))
        self.assertIsNone(rules.opening_period(at(9, 59), time(10), time(23)))
        self.assertIsNone(rules.opening_period(at(23), time(10), time(23)))  # closing time is exclusive

    def test_after_midnight_belongs_to_the_evening_before(self):
        evening = (at(10, day=DAY - timedelta(days=1)), at(2))
        self.assertEqual(rules.opening_period(at(1), time(10), time(2)), evening)
        self.assertIsNone(rules.opening_period(at(3), time(10), time(2)))
        self.assertEqual(rules.opening_period(at(22), time(10), time(2)), (at(10), at(2, day=DAY + timedelta(days=1))))

    def test_open_24_hours(self):
        self.assertIsNotNone(rules.opening_period(at(3), time(0), time(0)))


class CheckTimesTests(SimpleTestCase):
    def test_valid(self):
        self.assertIsNone(rules.check_times(at(12), 60, NOW, NORMAL))
        self.assertIsNone(rules.check_times(at(12), 90, NOW, NORMAL))

    def test_length(self):
        self.assertIn("at least 60 minutes", rules.check_times(at(12), 30, NOW, NORMAL))
        self.assertIn("steps of 30 minutes", rules.check_times(at(12), 75, NOW, NORMAL))

    def test_start_on_step_unless_start_now(self):
        self.assertEqual(rules.check_times(at(12, 10), 60, NOW, NORMAL), "Start times are every 30 minutes.")
        self.assertIsNone(rules.check_times(at(12, 10), 60, at(12, 10), NORMAL, start_now=True))
        self.assertIsNone(rules.check_times(at(12, 15), 60, NOW, cafe(step=15)))

    def test_past_start(self):
        self.assertIn("has passed", rules.check_times(at(12), 60, at(12, 5), NORMAL))

    def test_too_far_ahead(self):
        self.assertIn("up to 7 days ahead", rules.check_times(at(12) + timedelta(days=8), 60, NOW, NORMAL))

    def test_closed_and_closing(self):
        self.assertEqual(rules.check_times(at(9, 30), 60, at(8), NORMAL), "The café is closed at that time.")
        self.assertIsNone(rules.check_times(at(22), 60, NOW, NORMAL))  # ends exactly at closing
        self.assertIn("closes at 23:00", rules.check_times(at(22, 30), 60, NOW, NORMAL))

    def test_booking_across_midnight(self):
        self.assertIsNone(rules.check_times(at(23, 30), 90, NOW, LATE))  # 23:30–01:00
        self.assertIn("closes at 02:00", rules.check_times(at(1, 30, DAY + timedelta(days=1)), 60, NOW, LATE))

    def test_open_24_hours_has_no_closing(self):
        self.assertIsNone(rules.check_times(at(23, 30), 180, NOW, ALWAYS))


class CancelTests(SimpleTestCase):
    def test_cutoff_boundary(self):
        start = at(14)
        self.assertTrue(rules.can_cancel(start, at(12), 120))
        self.assertFalse(rules.can_cancel(start, at(12) + timedelta(seconds=1), 120))
        self.assertEqual(rules.cancel_deadline(start, 120), at(12))


class FormChoiceTests(SimpleTestCase):
    def test_start_times_today_skip_the_past(self):
        times = rules.start_times(DAY, at(12, 10), NORMAL)
        self.assertEqual((times[0], times[-1]), (at(12, 30), at(22)))

    def test_start_times_run_past_midnight(self):
        times = rules.start_times(DAY, NOW, LATE)
        self.assertEqual(times[-1], at(1, day=DAY + timedelta(days=1)))

    def test_booking_days_after_midnight_start_with_yesterday(self):
        days = rules.booking_days(at(0, 30), LATE)
        self.assertEqual(days[0], DAY - timedelta(days=1))
        self.assertEqual(len(days), 8)

    def test_booking_days_when_closed_start_today(self):
        self.assertEqual(rules.booking_days(at(8), NORMAL)[0], DAY)

    def test_lengths(self):
        self.assertEqual(rules.lengths(NORMAL)[:3], [60, 90, 120])
        self.assertEqual(rules.lengths(NORMAL)[-1], 12 * 60)

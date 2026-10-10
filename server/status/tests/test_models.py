from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from status.models import PC, CafeSettings
from status.state import IN_USE, Last


class CafeSettingsTests(TestCase):
    def test_load_creates_one_row_with_spec_defaults(self):
        first, second = CafeSettings.load(), CafeSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(CafeSettings.objects.count(), 1)
        self.assertEqual(
            (first.idle_threshold_s, first.offline_timeout_s, first.heartbeat_interval_s,
             first.agents_enabled, first.allow_new_pcs),
            (600, 180, 60, True, False),
        )

    def test_timeout_must_cover_two_heartbeats(self):
        with self.assertRaises(ValidationError):
            CafeSettings(heartbeat_interval_s=120, offline_timeout_s=180).full_clean()
        CafeSettings(heartbeat_interval_s=60, offline_timeout_s=180).full_clean()  # fine


class BookingSettingsTests(TestCase):
    def test_booking_defaults(self):
        cafe = CafeSettings.load()
        self.assertEqual(
            (cafe.hourly_rate_rupees, cafe.booking_step_min, cafe.min_booking_min, cafe.cancel_cutoff_min, cafe.advance_days),
            (100, 30, 60, 120, 7),
        )
        self.assertEqual((cafe.opens_at, cafe.closes_at), (time(10), time(23)))
        self.assertEqual(cafe.cafe_name, "Gaming Café")

    def test_min_length_must_be_whole_steps(self):
        with self.assertRaises(ValidationError):
            CafeSettings(booking_step_min=30, min_booking_min=45).full_clean()
        CafeSettings(booking_step_min=15, min_booking_min=45).full_clean()

    def test_same_open_and_close_means_24_hours(self):
        CafeSettings(opens_at=time(0), closes_at=time(0)).full_clean()  # allowed


class PCTests(TestCase):
    def test_last_mirrors_live_fields(self):
        seen = timezone.now()
        pc = PC.objects.create(
            hostname="PC07", last_seen_at=seen, last_event="boot",
            idle_s_at_last_seen=5, state=IN_USE, state_since=seen,
        )
        self.assertEqual(pc.last(), Last(seen, "boot", 5, IN_USE, seen))

    def test_new_pc_is_off_and_shown_by_label(self):
        pc = PC.objects.create(hostname="PC07", label="Seat 7")
        self.assertEqual(pc.state, "off")
        self.assertEqual(str(pc), "Seat 7")

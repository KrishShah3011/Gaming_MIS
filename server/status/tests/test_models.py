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

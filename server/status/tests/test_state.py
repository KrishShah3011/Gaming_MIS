from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from status.state import IDLE, IN_USE, OFF, Last, compute_state

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
THR, TIMEOUT = 600, 180


def s(seconds):
    return timedelta(seconds=seconds)


def last(state=IN_USE, idle_s=0, event="heartbeat", since=T0):
    """What the server knew after a heartbeat received at T0."""
    return Last(seen_at=T0, event=event, idle_s=idle_s, state=state, since=since)


NEVER_SEEN = Last(seen_at=None, event="", idle_s=0, state=OFF, since=None)


class ComputeStateTests(SimpleTestCase):
    def test_never_seen_is_off(self):
        self.assertEqual(compute_state(NEVER_SEEN, T0, THR, TIMEOUT), (OFF, None))

    def test_shutdown_is_off_immediately(self):
        self.assertEqual(compute_state(last(event="shutdown"), T0, THR, TIMEOUT), (OFF, T0))

    def test_off_exactly_at_timeout(self):
        self.assertEqual(compute_state(last(), T0 + s(180), THR, TIMEOUT), (OFF, T0 + s(180)))

    def test_not_off_one_second_before_timeout(self):
        self.assertEqual(compute_state(last(), T0 + s(179), THR, TIMEOUT)[0], IN_USE)

    def test_idle_exactly_at_threshold(self):
        self.assertEqual(compute_state(last(idle_s=540), T0 + s(60), THR, TIMEOUT), (IDLE, T0 + s(60)))

    def test_in_use_one_second_before_threshold(self):
        self.assertEqual(compute_state(last(idle_s=540), T0 + s(59), THR, TIMEOUT)[0], IN_USE)

    def test_idle_is_extrapolated_between_heartbeats(self):
        self.assertEqual(compute_state(last(idle_s=590), T0 + s(10), THR, TIMEOUT), (IDLE, T0 + s(10)))

    def test_unchanged_state_keeps_stored_since(self):
        earlier = T0 - s(900)
        result = compute_state(last(state=IDLE, idle_s=700, since=earlier), T0 + s(5), THR, TIMEOUT)
        self.assertEqual(result, (IDLE, earlier))

    def test_in_use_keeps_stored_since(self):
        earlier = T0 - s(300)
        result = compute_state(last(idle_s=3, since=earlier), T0 + s(30), THR, TIMEOUT)
        self.assertEqual(result, (IN_USE, earlier))

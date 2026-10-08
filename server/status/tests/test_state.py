from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from status.state import IDLE, IN_USE, OFF, Last, compute_state, settle

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


class SettleTests(SimpleTestCase):
    def settle(self, last_, event, idle_s, after, thr=THR):
        return settle(last_, event, idle_s, T0 + s(after), thr, TIMEOUT)

    def test_first_heartbeat_turns_on(self):
        self.assertEqual(settle(NEVER_SEEN, "boot", 0, T0, THR, TIMEOUT), [(IN_USE, T0)])

    def test_steady_use_records_nothing(self):
        self.assertEqual(self.settle(last(idle_s=5), "heartbeat", 3, after=60), [])

    def test_goes_idle_between_heartbeats_at_exact_time(self):
        self.assertEqual(self.settle(last(idle_s=590), "heartbeat", 650, after=60), [(IDLE, T0 + s(10))])

    def test_idle_exactly_at_threshold(self):
        self.assertEqual(self.settle(last(idle_s=540), "heartbeat", 600, after=60), [(IDLE, T0 + s(60))])

    def test_idle_pc_picked_up_again(self):
        idle = last(state=IDLE, idle_s=700, since=T0 - s(100))
        self.assertEqual(self.settle(idle, "heartbeat", 20, after=60), [(IN_USE, T0 + s(40))])

    def test_idle_and_back_between_two_heartbeats(self):
        self.assertEqual(
            self.settle(last(idle_s=590), "heartbeat", 30, after=60),
            [(IDLE, T0 + s(10)), (IN_USE, T0 + s(30))],
        )

    def test_silence_then_boot(self):
        self.assertEqual(
            self.settle(last(idle_s=5), "boot", 2, after=600),
            [(OFF, T0 + s(180)), (IN_USE, T0 + s(600))],
        )

    def test_went_idle_before_going_silent(self):
        self.assertEqual(
            self.settle(last(idle_s=500), "boot", 2, after=900),
            [(IDLE, T0 + s(100)), (OFF, T0 + s(180)), (IN_USE, T0 + s(900))],
        )

    def test_back_on_but_nobody_there_is_idle(self):
        self.assertEqual(
            self.settle(last(idle_s=5), "heartbeat", 700, after=900),
            [(OFF, T0 + s(180)), (IDLE, T0 + s(900))],
        )

    def test_shutdown_message_is_off_now(self):
        self.assertEqual(self.settle(last(idle_s=5), "shutdown", 0, after=60), [(OFF, T0 + s(60))])

    def test_idle_then_shutdown(self):
        self.assertEqual(
            self.settle(last(idle_s=590), "shutdown", 650, after=60),
            [(IDLE, T0 + s(10)), (OFF, T0 + s(60))],
        )

    def test_boot_after_shutdown_records_only_the_boot(self):
        shut = last(state=OFF, idle_s=700, event="shutdown")
        self.assertEqual(self.settle(shut, "boot", 1, after=300), [(IN_USE, T0 + s(300))])

    def test_shutdown_after_long_silence(self):
        self.assertEqual(self.settle(last(idle_s=5), "shutdown", 10, after=600), [(OFF, T0 + s(180))])

    def test_threshold_lowered_never_backdates_before_last_heartbeat(self):
        # At T0 the PC was in use with 300 s idle (threshold was 600). Admin then lowers it to 120.
        self.assertEqual(self.settle(last(idle_s=300), "heartbeat", 360, after=60, thr=120), [(IDLE, T0)])

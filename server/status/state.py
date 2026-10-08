"""PC state rules (first_milestone.md §6.2). Pure functions, no Django: easy to test.

Every state follows from the last heartbeat plus the clock, so there is no background job.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

OFF, IN_USE, IDLE = "off", "in_use", "idle"


@dataclass(frozen=True)
class Last:
    """What the server knew about a PC after its most recent heartbeat."""

    seen_at: datetime | None  # None = never reported
    event: str  # "boot" | "heartbeat" | "shutdown" | ""
    idle_s: int  # seconds since last input, as reported at seen_at
    state: str  # state stored at seen_at
    since: datetime | None  # when the stored state began


def idle_at(last: Last, idle_threshold_s: int) -> datetime:
    """When the PC goes (or went) Idle if nobody touches it."""
    return last.seen_at - timedelta(seconds=last.idle_s) + timedelta(seconds=idle_threshold_s)


def off_at(last: Last, offline_timeout_s: int) -> datetime:
    """When the PC counts as Off: at once after a shutdown, else after the silence timeout."""
    if last.event == "shutdown":
        return last.seen_at
    return last.seen_at + timedelta(seconds=offline_timeout_s)


def compute_state(last: Last, now: datetime, idle_threshold_s: int, offline_timeout_s: int):
    """Live (state, since) at `now`. Read-only; the dashboard calls it on every load."""
    if last.seen_at is None:
        return OFF, None
    went_off = off_at(last, offline_timeout_s)
    if now >= went_off:
        return OFF, last.since if last.state == OFF else went_off
    went_idle = idle_at(last, idle_threshold_s)
    if now >= went_idle:
        return IDLE, last.since if last.state == IDLE else went_idle
    return IN_USE, last.since if last.state == IN_USE else last.seen_at


def settle(last: Last, event: str, idle_s: int, now: datetime, idle_threshold_s: int, offline_timeout_s: int):
    """State changes since the previous heartbeat, with exact times, oldest first.

    The new heartbeat tells us when the last input happened (now - idle_s), which lets
    us write history that the dashboard could only guess at. Accuracy is limited by the
    heartbeat interval: of all input between two heartbeats, only the last is visible.
    """
    last_input = now - timedelta(seconds=idle_s)
    timeline = []
    back_on = last.seen_at is None
    if not back_on:
        went_idle = idle_at(last, idle_threshold_s)
        went_off = off_at(last, offline_timeout_s)
        if now >= went_off:  # shut down, or silent too long: it was off in between
            if last.event != "shutdown" and went_idle < went_off:
                timeline.append((IDLE, went_idle))
            timeline.append((OFF, went_off))
            back_on = True
        elif went_idle < last_input:  # went idle, then someone touched it again
            timeline += [(IDLE, went_idle), (IN_USE, last_input)]

    if back_on:
        if event != "shutdown":
            timeline.append((IDLE if idle_s >= idle_threshold_s else IN_USE, now))
    elif now >= last_input + timedelta(seconds=idle_threshold_s):
        timeline.append((IDLE, last_input + timedelta(seconds=idle_threshold_s)))
    else:
        timeline.append((IN_USE, last_input))
    if event == "shutdown":
        timeline.append((OFF, now))

    changes, current, floor = [], last.state, last.seen_at or now
    for state, at in timeline:
        at = max(at, floor)  # never before the last heartbeat (e.g. threshold lowered mid-way)
        if state != current:
            changes.append((state, at))
            current, floor = state, at
    return changes

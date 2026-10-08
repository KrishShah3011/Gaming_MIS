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

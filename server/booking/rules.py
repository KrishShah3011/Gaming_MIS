"""Booking rules (m2 spec §5). Pure functions, no Django: easy to test.

Datetimes are timezone-aware and already in café local time. `s` is anything with the CafeSettings
booking fields: booking_step_min, min_booking_min, advance_days, opens_at, closes_at.
"""
from datetime import datetime, timedelta

MAX_LENGTH_MIN = 12 * 60  # longest length the booking form offers


def price_paise(rate_rupees, minutes):
    """Hourly rate × length, rounded half-up to the paise."""
    return (rate_rupees * 100 * minutes * 2 + 60) // 120


def _period(day, opens, closes, tz):
    """The opening period that begins on `day`. Closing at or before opening means the next day."""
    close_day = day if closes > opens else day + timedelta(days=1)
    return datetime.combine(day, opens, tz), datetime.combine(close_day, closes, tz)


def opening_period(at, opens, closes):
    """(open, close) of the opening period containing `at`, or None if the café is closed then."""
    if opens == closes:  # open around the clock: no closing time to respect
        return at, datetime.max.replace(tzinfo=at.tzinfo)
    for day in (at.date() - timedelta(days=1), at.date()):
        open_dt, close_dt = _period(day, opens, closes, at.tzinfo)
        if open_dt <= at < close_dt:
            return open_dt, close_dt
    return None


def check_times(start, minutes, now, s, start_now=False):
    """Why [start, start + minutes) can't be booked, in words for the customer; None if it can."""
    step = s.booking_step_min
    if minutes < s.min_booking_min or minutes % step:
        return f"Pick a length of at least {s.min_booking_min} minutes, in steps of {step} minutes."
    if not start_now:
        if start.minute % step or start.second or start.microsecond:
            return f"Start times are every {step} minutes."
        if start < now:
            return "That start time has passed. Pick a later one."
    if start - now > timedelta(days=s.advance_days):
        return f"You can book up to {s.advance_days} days ahead."
    period = opening_period(start, s.opens_at, s.closes_at)
    if period is None:
        return "The café is closed at that time."
    if start + timedelta(minutes=minutes) > period[1]:
        return f"The café closes at {period[1]:%H:%M}. Pick a shorter length."
    return None


def cancel_deadline(start, cutoff_min):
    return start - timedelta(minutes=cutoff_min)


def can_cancel(start, now, cutoff_min):
    return now <= cancel_deadline(start, cutoff_min)


def booking_days(now, s):
    """Days to pick from: the opening day in progress (or today), then the next `advance_days`."""
    current = opening_period(now, s.opens_at, s.closes_at)
    first = current[0].date() if current else now.date()
    return [first + timedelta(days=i) for i in range(s.advance_days + 1)]


def start_times(day, now, s):
    """Future start times, every step, in the opening period that begins on `day`."""
    open_dt, close_dt = _period(day, s.opens_at, s.closes_at, now.tzinfo)
    step = timedelta(minutes=s.booking_step_min)
    latest = min(close_dt - timedelta(minutes=s.min_booking_min), now + timedelta(days=s.advance_days))
    times, t = [], open_dt
    while t <= latest:
        if t >= now:
            times.append(t)
        t += step
    return times


def lengths(s):
    return list(range(s.min_booking_min, MAX_LENGTH_MIN + 1, s.booking_step_min))

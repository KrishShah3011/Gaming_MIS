"""Booking and wallet operations (m2 spec §5–6). Every rupee movement is a WalletEntry row."""
from datetime import timedelta
from uuid import uuid4

from django.db import IntegrityError, OperationalError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.db.models import Sum
from django.utils import timezone

from status.models import PC, CafeSettings
from status.state import IN_USE, compute_state

from . import rules
from .models import Booking, Customer, Offer, TopUpOrder, WalletEntry

TOPUP_MIN_RUPEES, TOPUP_MAX_RUPEES = 100, 10_000
TIME_UP_HIDE_AFTER = timedelta(hours=6)


class BookingError(Exception):
    """A request was refused. str(error) is shown to the customer as-is."""


def balance_paise(customer):
    return customer.wallet_entries.aggregate(total=Sum("amount_paise"))["total"] or 0


def paid_paise(booking):
    """Everything paid for this booking: the booking plus any added time."""
    kinds = [WalletEntry.BOOKING, WalletEntry.EXTENSION]
    return -(booking.wallet_entries.filter(kind__in=kinds).aggregate(total=Sum("amount_paise"))["total"] or 0)


def _live_bookings():
    return Booking.objects.filter(cancelled_at__isnull=True)


def _in_use_pc_ids(now, cafe):
    return {
        pc.id for pc in PC.objects.filter(is_active=True)
        if compute_state(pc.last(), now, cafe.idle_threshold_s, cafe.offline_timeout_s)[0] == IN_USE
    }


def seat_map(start, end, now, cafe, start_now=False):
    """Every active PC with whether it's free for [start, end).

    free_until: when a PC is free at `start` but has a later booking, that booking's start.
    For "Start now", a PC that is In Use with no booking (someone sitting there) is taken.
    """
    taken = set(_live_bookings().filter(period__overlap=DateTimeTZRange(start, end)).values_list("pc_id", flat=True))
    in_use = _in_use_pc_ids(now, cafe) if start_now else set()
    first_after = {}
    for pc_id, period in _live_bookings().filter(period__endswith__gt=start).order_by("period").values_list("pc_id", "period"):
        first_after.setdefault(pc_id, period.lower)
    return [
        {
            "pc": pc,
            "free": pc.id not in taken | in_use,
            "free_until": None if pc.id in in_use or first_after.get(pc.id, start) <= start else first_after[pc.id],
        }
        for pc in PC.objects.filter(is_active=True)
    ]


def book(customer, pc_ids, start, minutes, now, start_now=False):
    """Book the PCs for `minutes` from `start` (or from now) and pay from the wallet."""
    cafe = CafeSettings.load()
    if start_now:
        start = now.replace(second=0, microsecond=0)
    error = rules.check_times(timezone.localtime(start), minutes, timezone.localtime(now), cafe, start_now)
    if error:
        raise BookingError(error)
    wanted = set(pc_ids)
    pcs = list(PC.objects.filter(id__in=wanted, is_active=True))
    if not pcs or len(pcs) != len(wanted):
        raise BookingError("Pick at least one available PC.")
    end = start + timedelta(minutes=minutes)
    busy = [seat["pc"] for seat in seat_map(start, end, now, cafe, start_now) if seat["pc"].id in wanted and not seat["free"]]
    if busy:
        raise BookingError(f"{busy[0]} isn't free for that time. Pick another seat.")
    price = rules.price_paise(cafe.hourly_rate_rupees, minutes)
    group, bookings = uuid4(), []
    try:
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=customer.pk)  # one spend at a time per wallet
            if balance_paise(customer) < price * len(pcs):
                raise BookingError("Not enough balance. Top up to book.")
            for pc in pcs:
                booking = Booking.objects.create(customer=customer, pc=pc, group=group, period=DateTimeTZRange(start, end))
                WalletEntry.objects.create(customer=customer, amount_paise=-price, kind=WalletEntry.BOOKING, booking=booking, at=now)
                bookings.append(booking)
    except (IntegrityError, OperationalError):  # the no-overlap constraint: someone booked a seat a moment ago
        raise BookingError("One of those PCs was just booked by someone else. Pick another seat.") from None
    return bookings


def cancel(booking, now, by_staff=False):
    """Cancel one booked PC and refund everything paid for it to the wallet. Returns the refund."""
    cafe = CafeSettings.load()
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.cancelled_at:
            raise BookingError("This booking is already cancelled.")
        if not by_staff and not rules.can_cancel(booking.start, now, cafe.cancel_cutoff_min):
            deadline = timezone.localtime(rules.cancel_deadline(booking.start, cafe.cancel_cutoff_min))
            raise BookingError(f"Cancellation closed at {deadline:%H:%M on %d %b}.")
        refund = paid_paise(booking)
        booking.cancelled_at = now
        booking.save(update_fields=["cancelled_at"])
        WalletEntry.objects.create(customer=booking.customer, amount_paise=refund, kind=WalletEntry.REFUND, booking=booking, at=now)
    return refund


def extend(booking, minutes, now):
    """Add time to a current or upcoming booking, paid from the wallet. Returns the price."""
    cafe = CafeSettings.load()
    if minutes <= 0 or minutes % cafe.booking_step_min:
        raise BookingError(f"Add time in steps of {cafe.booking_step_min} minutes.")
    price = rules.price_paise(cafe.hourly_rate_rupees, minutes)
    try:
        with transaction.atomic():
            Customer.objects.select_for_update().get(pk=booking.customer_id)
            booking = Booking.objects.select_for_update().get(pk=booking.pk)
            if booking.cancelled_at or booking.end <= now:
                raise BookingError("This booking has ended.")
            new_end = booking.end + timedelta(minutes=minutes)
            period = rules.opening_period(timezone.localtime(booking.start), cafe.opens_at, cafe.closes_at)
            if period is None or new_end > period[1]:
                raise BookingError("That goes past closing time. Add less time.")
            if balance_paise(booking.customer) < price:
                raise BookingError("Not enough balance. Top up to add time.")
            booking.period = DateTimeTZRange(booking.start, new_end)
            booking.save(update_fields=["period"])
            WalletEntry.objects.create(customer=booking.customer, amount_paise=-price, kind=WalletEntry.EXTENSION, booking=booking, at=now)
    except IntegrityError:
        raise BookingError(f"{booking.pc} is booked right after you, so time can't be added.") from None
    return price


def live_offers(now, cafe):
    """Active offers, each with `.hours`: what the top-up plus bonus buys at the current rate."""
    offers = list(Offer.live(now))
    for offer in offers:
        offer.hours = (offer.pay_rupees + offer.bonus_rupees) / cafe.hourly_rate_rupees
    return offers


def topup_terms(amount_rupees, offer, now):
    """(amount_paise, bonus_paise, offer) for a top-up. A typed amount equal to an offer gets its bonus."""
    if offer is None:
        if not TOPUP_MIN_RUPEES <= amount_rupees <= TOPUP_MAX_RUPEES:
            raise BookingError(f"Top up between ₹{TOPUP_MIN_RUPEES} and ₹{TOPUP_MAX_RUPEES:,}.")
        offer = Offer.live(now).filter(pay_rupees=amount_rupees).first()
        if offer is None:
            return amount_rupees * 100, 0, None
    elif not offer.is_valid(now):
        raise BookingError("That offer has ended. Pick another amount.")
    return offer.pay_rupees * 100, offer.bonus_rupees * 100, offer


def credit_topup(order, payment_id, now):
    """Credit a paid Razorpay order (and its bonus) once. False if it was already credited."""
    with transaction.atomic():
        order = TopUpOrder.objects.select_for_update().get(pk=order.pk)
        if order.paid_at:
            return False
        WalletEntry.objects.create(customer=order.customer, amount_paise=order.amount_paise,
                                   kind=WalletEntry.TOPUP_ONLINE, razorpay_payment_id=payment_id, at=now)
        if order.bonus_paise:
            WalletEntry.objects.create(customer=order.customer, amount_paise=order.bonus_paise,
                                       kind=WalletEntry.BONUS, note=order.offer.name if order.offer else "", at=now)
        order.paid_at = now
        order.save(update_fields=["paid_at"])
    return True


def time_up(now):
    """Ended bookings staff haven't marked Cleared. Hidden 6 hours after the end."""
    return (
        _live_bookings()
        .filter(cleared_at__isnull=True, period__endswith__lte=now, period__endswith__gt=now - TIME_UP_HIDE_AFTER)
        .select_related("customer__user", "pc")
        .order_by("period")
    )


def tile_bookings(now):
    """{pc_id: {"now": booking playing now, "next": next booking in the coming 12 hours}}."""
    tiles = {}
    upcoming = _live_bookings().filter(period__endswith__gt=now, period__startswith__lt=now + timedelta(hours=12))
    for booking in upcoming.select_related("customer__user").order_by("period"):
        slot = tiles.setdefault(booking.pc_id, {"now": None, "next": None})
        if booking.start <= now:
            slot["now"] = booking
        elif slot["next"] is None:
            slot["next"] = booking
    return tiles

from datetime import timedelta
from uuid import uuid4

from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import TestCase
from django.utils import timezone

from booking import services
from booking.models import Booking, Offer, TopUpOrder
from booking.services import BookingError
from status.models import CafeSettings

from .helpers import make_customer, make_pcs, open_24h, tomorrow_at


class BookTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer(rupees=1000)
        self.now, self.start = timezone.now(), tomorrow_at(12)

    def test_books_several_pcs_and_charges_each(self):
        bookings = services.book(self.customer, [self.pc1.id, self.pc2.id], self.start, 90, self.now)
        self.assertEqual(len(bookings), 2)
        self.assertEqual(len({b.group for b in bookings}), 1)
        self.assertEqual(services.balance_paise(self.customer), 100000 - 2 * 15000)
        self.assertEqual(services.paid_paise(bookings[0]), 15000)

    def test_exact_balance_is_enough(self):
        exact = make_customer("ravi", rupees=100)
        services.book(exact, [self.pc1.id], self.start, 60, self.now)
        self.assertEqual(services.balance_paise(exact), 0)

    def test_not_enough_balance(self):
        poor = make_customer("ravi", rupees=100)
        with self.assertRaisesMessage(BookingError, "Not enough balance"):
            services.book(poor, [self.pc1.id], self.start, 90, self.now)
        self.assertFalse(Booking.objects.exists())

    def test_one_taken_pc_fails_the_whole_request(self):
        services.book(make_customer("ravi", rupees=500), [self.pc2.id], self.start, 60, self.now)
        with self.assertRaisesMessage(BookingError, "PC02 isn't free for that time"):
            services.book(self.customer, [self.pc1.id, self.pc2.id], self.start, 60, self.now)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(services.balance_paise(self.customer), 100000)

    def test_bad_times_are_refused(self):
        with self.assertRaisesMessage(BookingError, "Start times are every 30 minutes"):
            services.book(self.customer, [self.pc1.id], tomorrow_at(12, 10), 60, self.now)

    def test_inactive_or_missing_pc_is_refused(self):
        self.pc1.is_active = False
        self.pc1.save()
        for pc_ids in ([self.pc1.id], [], [999]):
            with self.assertRaisesMessage(BookingError, "Pick at least one available PC"):
                services.book(self.customer, pc_ids, self.start, 60, self.now)

    def test_start_now_skips_a_pc_in_use(self):
        self.pc1.last_seen_at, self.pc1.last_event, self.pc1.state = self.now, "heartbeat", "in_use"
        self.pc1.save()
        with self.assertRaisesMessage(BookingError, "PC01 isn't free"):
            services.book(self.customer, [self.pc1.id], None, 60, self.now, start_now=True)
        [booking] = services.book(self.customer, [self.pc2.id], None, 60, self.now, start_now=True)  # Off is free
        self.assertEqual(booking.start, self.now.replace(second=0, microsecond=0))


class SeatMapTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.now, self.start = timezone.now(), tomorrow_at(12)
        services.book(make_customer(rupees=500), [self.pc1.id], tomorrow_at(14), 60, self.now)

    def test_free_taken_and_free_until(self):
        cafe = CafeSettings.load()
        short = {s["pc"].hostname: s for s in services.seat_map(self.start, tomorrow_at(13), self.now, cafe)}
        self.assertEqual((short["PC01"]["free"], short["PC01"]["free_until"]), (True, tomorrow_at(14)))
        self.assertEqual((short["PC02"]["free"], short["PC02"]["free_until"]), (True, None))
        long = {s["pc"].hostname: s for s in services.seat_map(self.start, tomorrow_at(15), self.now, cafe)}
        self.assertEqual((long["PC01"]["free"], long["PC01"]["free_until"]), (False, tomorrow_at(14)))
        during = {s["pc"].hostname: s for s in services.seat_map(tomorrow_at(14), tomorrow_at(15), self.now, cafe)}
        self.assertEqual((during["PC01"]["free"], during["PC01"]["free_until"]), (False, None))


class CancelExtendTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer(rupees=1000)
        self.now, self.start = timezone.now(), tomorrow_at(12)
        self.b1, self.b2 = services.book(self.customer, [self.pc1.id, self.pc2.id], self.start, 60, self.now)

    def balance(self):
        return services.balance_paise(self.customer)

    def test_partial_cancel_refunds_only_that_pc(self):
        self.assertEqual(services.cancel(self.b1, self.start - timedelta(minutes=120)), 10000)
        self.assertEqual(self.balance(), 100000 - 10000)
        self.b2.refresh_from_db()
        self.assertIsNone(self.b2.cancelled_at)

    def test_after_cutoff_customers_cannot_cancel_but_staff_can(self):
        late = self.start - timedelta(minutes=119)
        with self.assertRaisesMessage(BookingError, "Cancellation closed at"):
            services.cancel(self.b1, late)
        self.assertEqual(services.cancel(self.b1, late, by_staff=True), 10000)

    def test_cancel_twice_is_refused(self):
        services.cancel(self.b1, self.now)
        with self.assertRaisesMessage(BookingError, "already cancelled"):
            services.cancel(self.b1, self.now)

    def test_refund_uses_price_paid_not_new_rate(self):
        cafe = CafeSettings.load()
        cafe.hourly_rate_rupees = 300
        cafe.save()
        self.assertEqual(services.cancel(self.b1, self.now), 10000)

    def test_extend_charges_extra_and_cancel_refunds_all(self):
        self.assertEqual(services.extend(self.b1, 30, self.now), 5000)
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.end, self.start + timedelta(minutes=90))
        self.assertEqual(services.cancel(self.b1, self.now), 15000)
        self.assertEqual(self.balance(), 100000 - 10000)

    def test_extend_into_next_booking_is_refused_and_free(self):
        services.book(make_customer("ravi", rupees=500), [self.pc1.id], self.start + timedelta(hours=1), 60, self.now)
        with self.assertRaisesMessage(BookingError, "PC01 is booked right after you"):
            services.extend(self.b1, 30, self.now)
        self.assertEqual(self.balance(), 100000 - 20000)

    def test_extend_needs_whole_steps(self):
        with self.assertRaisesMessage(BookingError, "steps of 30 minutes"):
            services.extend(self.b1, 20, self.now)

    def test_extend_after_end_is_refused(self):
        with self.assertRaisesMessage(BookingError, "This booking has ended"):
            services.extend(self.b1, 30, self.start + timedelta(hours=2))

    def test_extend_needs_balance(self):
        poor = make_customer("ravi", rupees=100)
        [booking] = services.book(poor, [self.pc1.id], tomorrow_at(18), 60, self.now)
        with self.assertRaisesMessage(BookingError, "Not enough balance"):
            services.extend(booking, 30, self.now)


class ExtendClosingTests(TestCase):
    def test_extend_past_closing_is_refused(self):  # default hours 10:00–23:00
        [pc] = make_pcs(1)
        customer = make_customer(rupees=1000)
        [booking] = services.book(customer, [pc.id], tomorrow_at(22), 60, timezone.now())
        with self.assertRaisesMessage(BookingError, "past closing time"):
            services.extend(booking, 30, timezone.now())


class TopUpTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_custom_amount_limits(self):
        self.assertEqual(services.topup_terms(100, None, self.now), (10000, 0, None))
        for amount in (99, 10001):
            with self.assertRaisesMessage(BookingError, "Top up between ₹100 and ₹10,000"):
                services.topup_terms(amount, None, self.now)

    def test_offer_and_matching_amount_get_the_bonus(self):
        offer = Offer.objects.create(name="Pay 500, get 6 hrs", pay_rupees=500, bonus_rupees=100)
        self.assertEqual(services.topup_terms(1, offer, self.now), (50000, 10000, offer))
        self.assertEqual(services.topup_terms(500, None, self.now), (50000, 10000, offer))

    def test_expired_offer(self):
        offer = Offer.objects.create(name="Old", pay_rupees=500, bonus_rupees=100, valid_until=self.now - timedelta(minutes=1))
        with self.assertRaisesMessage(BookingError, "That offer has ended"):
            services.topup_terms(0, offer, self.now)
        self.assertEqual(services.topup_terms(500, None, self.now), (50000, 0, None))

    def test_credit_topup_twice_credits_once(self):
        customer = make_customer()
        order = TopUpOrder.objects.create(razorpay_order_id="order_1", customer=customer, amount_paise=50000, bonus_paise=10000)
        self.assertTrue(services.credit_topup(order, "pay_1", self.now))
        self.assertFalse(services.credit_topup(order, "pay_1", self.now))
        self.assertEqual(services.balance_paise(customer), 60000)
        order.refresh_from_db()
        self.assertIsNotNone(order.paid_at)

    def test_live_offers_have_hours(self):
        Offer.objects.create(name="Pay 500", pay_rupees=500, bonus_rupees=100)
        [offer] = services.live_offers(self.now, CafeSettings.load())
        self.assertEqual(offer.hours, 6)


class StaffQueryTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer(rupees=1000)
        self.now = timezone.now()

    def test_time_up_and_tiles(self):
        def booking(pc, start_min, end_min, **extra):
            return Booking.objects.create(customer=self.customer, pc=pc, group=uuid4(), period=DateTimeTZRange(
                self.now + timedelta(minutes=start_min), self.now + timedelta(minutes=end_min)), **extra)
        ended = booking(self.pc1, -70, -10)
        booking(self.pc1, -500, -430)  # ended over 6 h ago: hidden
        booking(self.pc2, -60, -5, cancelled_at=self.now)  # cancelled: never time up
        current = booking(self.pc2, -5, 55)
        upcoming = booking(self.pc1, 60, 120)
        self.assertEqual(list(services.time_up(self.now)), [ended])
        tiles = services.tile_bookings(self.now)
        self.assertEqual(tiles[self.pc2.id], {"now": current, "next": None})
        self.assertEqual(tiles[self.pc1.id], {"now": None, "next": upcoming})

from datetime import timedelta
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import TestCase
from django.utils import timezone

from booking.models import Booking, Offer, WalletEntry
from status.models import PC

from .helpers import make_customer, make_pcs, tomorrow_at


class BookingConstraintTests(TestCase):
    def setUp(self):
        self.customer = make_customer()
        self.pc1, self.pc2 = make_pcs(2)
        self.t0 = tomorrow_at(12)

    def book(self, start_h, end_h, pc=None):
        return Booking.objects.create(
            customer=self.customer, pc=pc or self.pc1, group=uuid4(),
            period=DateTimeTZRange(self.t0 + timedelta(hours=start_h), self.t0 + timedelta(hours=end_h)),
        )

    def test_overlap_on_same_pc_is_refused(self):
        self.book(0, 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.book(1, 3)

    def test_back_to_back_is_allowed(self):
        self.book(0, 2)
        self.book(2, 3)

    def test_other_pc_same_time_is_allowed(self):
        self.book(0, 2)
        self.book(0, 2, pc=self.pc2)

    def test_cancelled_booking_frees_the_slot(self):
        first = self.book(0, 2)
        first.cancelled_at = timezone.now()
        first.save()
        self.book(0, 2)

    def test_start_and_end(self):
        booking = self.book(0, 2)
        booking.refresh_from_db()
        self.assertEqual((booking.start, booking.end), (self.t0, self.t0 + timedelta(hours=2)))


class WalletEntryTests(TestCase):
    def test_a_payment_id_is_credited_once(self):
        customer = make_customer()
        WalletEntry.objects.create(customer=customer, amount_paise=50000, kind=WalletEntry.TOPUP_ONLINE,
                                   razorpay_payment_id="pay_1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            WalletEntry.objects.create(customer=customer, amount_paise=50000, kind=WalletEntry.TOPUP_ONLINE,
                                       razorpay_payment_id="pay_1")
        # Entries without a payment ID never collide.
        WalletEntry.objects.create(customer=customer, amount_paise=100, kind=WalletEntry.BONUS)
        WalletEntry.objects.create(customer=customer, amount_paise=100, kind=WalletEntry.BONUS)


class OfferTests(TestCase):
    def test_live_offers(self):
        now = timezone.now()
        live = Offer.objects.create(name="Pay 500", pay_rupees=500, bonus_rupees=100)
        Offer.objects.create(name="Off", pay_rupees=300, bonus_rupees=50, is_active=False)
        Offer.objects.create(name="Expired", pay_rupees=200, bonus_rupees=20, valid_until=now - timedelta(minutes=1))
        self.assertEqual(list(Offer.live(now)), [live])
        self.assertTrue(live.is_valid(now))


class CustomerTests(TestCase):
    def test_name(self):
        customer = make_customer("asha")
        self.assertEqual((str(customer), customer.first_name), ("Asha", "Asha"))

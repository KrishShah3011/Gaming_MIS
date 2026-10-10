from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from booking import services
from booking.models import Booking, Offer, WalletEntry

from .helpers import make_customer, make_pcs, open_24h, tomorrow_at

ADD = "/admin/booking/walletentry/add/"


class WalletAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("boss", password="pw-123456789")
        self.client.force_login(self.admin)
        self.customer = make_customer()
        self.offer = Offer.objects.create(name="Pay 500", pay_rupees=500, bonus_rupees=100)

    def add(self, **data):
        return self.client.post(ADD, {"customer": self.customer.pk, "note": "", "offer": "", "_save": "Save", **data})

    def test_cash_top_up_with_offer(self):
        response = self.add(kind="topup_cash", rupees="500", offer=self.offer.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(services.balance_paise(self.customer), 60000)
        cash = WalletEntry.objects.get(kind=WalletEntry.TOPUP_CASH)
        self.assertEqual((cash.amount_paise, cash.staff), (50000, self.admin))
        self.assertTrue(WalletEntry.objects.filter(kind=WalletEntry.BONUS, amount_paise=10000, staff=self.admin).exists())

    def test_offer_needs_its_exact_amount(self):
        self.assertContains(self.add(kind="topup_cash", rupees="400", offer=self.offer.pk), "This offer needs exactly ₹500.")
        self.assertFalse(WalletEntry.objects.exists())

    def test_correction_needs_a_reason_and_keeps_paise(self):
        self.assertContains(self.add(kind="correction", rupees="-24.75"), "Say why you&#x27;re correcting the balance.")
        self.add(kind="correction", rupees="-24.75", note="Gave cash back")
        self.assertEqual(services.balance_paise(self.customer), -2475)

    def test_entries_cannot_be_edited_or_deleted(self):
        entry = WalletEntry.objects.create(customer=self.customer, amount_paise=100, kind=WalletEntry.BONUS)
        url = f"/admin/booking/walletentry/{entry.pk}/change/"
        self.assertEqual(self.client.post(url, {"note": "x"}).status_code, 403)
        self.assertEqual(self.client.post(f"/admin/booking/walletentry/{entry.pk}/delete/", {"post": "yes"}).status_code, 403)

    def test_customer_page_shows_balance_and_links(self):
        WalletEntry.objects.create(customer=self.customer, amount_paise=12500, kind=WalletEntry.TOPUP_CASH)
        response = self.client.get(f"/admin/booking/customer/{self.customer.pk}/change/")
        self.assertContains(response, "₹125")
        self.assertContains(response, f"{ADD}?customer={self.customer.pk}&amp;kind=topup_cash")


class BookingAdminTests(TestCase):
    def test_cancel_and_refund_ignores_cutoff(self):
        open_24h()
        [pc] = make_pcs(1)
        customer = make_customer(rupees=500)
        [booking] = services.book(customer, [pc.id], None, 60, timezone.now(), start_now=True)
        self.client.force_login(User.objects.create_superuser("boss", password="pw-123456789"))
        self.client.post("/admin/booking/booking/", {"action": "cancel_and_refund", "index": "0", "_selected_action": [booking.pk]})
        booking.refresh_from_db()
        self.assertIsNotNone(booking.cancelled_at)
        self.assertEqual(services.balance_paise(customer), 50000)

    def test_filters_load(self):
        self.client.force_login(User.objects.create_superuser("boss", password="pw-123456789"))
        for when in ("now", "today", "upcoming", "past"):
            self.assertEqual(self.client.get(f"/admin/booking/booking/?when={when}").status_code, 200)

from django.test import TestCase
from django.utils import timezone

from booking import services

from .helpers import make_customer, make_pcs, open_24h, tomorrow_at


class MyBookingsTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer(rupees=1000)
        self.client.force_login(self.customer.user)
        self.b1, self.b2 = services.book(self.customer, [self.pc1.id, self.pc2.id], tomorrow_at(12), 60, timezone.now())

    def test_lists_upcoming_with_actions(self):
        response = self.client.get("/me/bookings/")
        self.assertContains(response, "PC01")
        self.assertContains(response, "Cancel and get ₹100 back")
        self.assertContains(response, "30 min for ₹50")

    def test_cancel_one_pc(self):
        response = self.client.post(f"/me/bookings/{self.b1.pk}/cancel", follow=True)
        self.assertContains(response, "Cancelled PC01. ₹100 is back in your wallet.")
        self.assertEqual(services.balance_paise(self.customer), 100000 - 10000)

    def test_cannot_touch_other_customers_booking(self):
        [other] = services.book(make_customer("ravi", rupees=500), [self.pc1.id], tomorrow_at(15), 60, timezone.now())
        self.assertEqual(self.client.post(f"/me/bookings/{other.pk}/cancel").status_code, 404)
        self.assertEqual(self.client.post(f"/me/bookings/{other.pk}/extend", {"minutes": 30}).status_code, 404)

    def test_started_booking_shows_cutoff_not_cancel(self):
        services.book(self.customer, [self.pc1.id], None, 60, timezone.now(), start_now=True)
        response = self.client.get("/me/bookings/")
        self.assertContains(response, "Playing now")
        self.assertContains(response, "Cancellation closed at")

    def test_add_time(self):
        response = self.client.post(f"/me/bookings/{self.b1.pk}/extend", {"minutes": 30}, follow=True)
        self.assertContains(response, "Added 30 min to PC01 for ₹50.")
        self.assertEqual(services.balance_paise(self.customer), 100000 - 25000)

    def test_add_time_bad_input(self):
        response = self.client.post(f"/me/bookings/{self.b1.pk}/extend", {"minutes": "abc"}, follow=True)
        self.assertContains(response, "Add time in steps of 30 minutes.")

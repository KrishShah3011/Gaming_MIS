from datetime import timedelta
from uuid import uuid4

from django.contrib.auth.models import User
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import TestCase
from django.utils import timezone

from booking.models import Booking

from .helpers import make_customer, make_pcs


class StaffDashboardTests(TestCase):
    def setUp(self):
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer("asha")
        self.staff = User.objects.create_user("staff", password="pw-123456789", is_staff=True)
        self.client.force_login(self.staff)
        self.now = timezone.now()

    def booking(self, pc, start_min, end_min, **extra):
        return Booking.objects.create(customer=self.customer, pc=pc, group=uuid4(), period=DateTimeTZRange(
            self.now + timedelta(minutes=start_min), self.now + timedelta(minutes=end_min)), **extra)

    def test_current_and_next_booking_on_tiles(self):
        current = self.booking(self.pc1, -10, 50)
        upcoming = self.booking(self.pc2, 60, 120)
        response = self.client.get("/staff/")
        self.assertContains(response, f"Asha, until {timezone.localtime(current.end):%H:%M}")
        self.assertContains(response, f"Next: {timezone.localtime(upcoming.start):%H:%M}")

    def test_time_up_until_cleared(self):
        ended = self.booking(self.pc1, -70, -10)
        response = self.client.get("/staff/")
        self.assertContains(response, "Time up: Asha")
        self.assertContains(response, f'action="/staff/bookings/{ended.pk}/clear"')
        self.assertContains(response, 'id="time-up"')
        self.assertRedirects(self.client.post(f"/staff/bookings/{ended.pk}/clear"), "/staff/", fetch_redirect_response=False)
        ended.refresh_from_db()
        self.assertEqual(ended.cleared_by, self.staff)
        self.assertNotContains(self.client.get("/staff/"), "Time up: Asha")

    def test_old_and_cancelled_bookings_are_not_time_up(self):
        self.booking(self.pc1, -500, -430)
        self.booking(self.pc2, -70, -10, cancelled_at=self.now)
        self.assertNotContains(self.client.get("/staff/"), "Time up:")

    def test_customers_cannot_clear(self):
        ended = self.booking(self.pc1, -70, -10)
        self.client.force_login(self.customer.user)
        self.client.post(f"/staff/bookings/{ended.pk}/clear")
        ended.refresh_from_db()
        self.assertIsNone(ended.cleared_at)

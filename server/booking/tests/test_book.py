from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from booking import services
from booking.models import Booking
from status.models import CafeSettings

from .helpers import make_customer, make_pcs, open_24h, tomorrow_at


class HomeTests(TestCase):
    def test_open_shows_free_count(self):
        open_24h()
        make_pcs(3)
        response = self.client.get("/")
        self.assertContains(response, "3 of 3 PCs free right now")
        self.assertContains(response, "Start now")

    def test_closed(self):
        cafe = CafeSettings.load()
        now = timezone.localtime()
        cafe.opens_at, cafe.closes_at = (now + timedelta(hours=2)).time(), (now + timedelta(hours=3)).time()
        cafe.save()
        response = self.client.get("/")
        self.assertContains(response, "Closed now")
        self.assertNotContains(response, "Start now")


class BookTests(TestCase):
    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.customer = make_customer(rupees=1000)
        self.client.force_login(self.customer.user)
        self.day = tomorrow_at(0).date().isoformat()

    def post(self, pcs, start="12:00", minutes=90):
        return self.client.post("/book/", {"day": self.day, "start": start, "minutes": minutes, "pc": pcs})

    def test_needs_sign_in(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/book/"), "/accounts/login/?next=/book/", fetch_redirect_response=False)

    def test_page_shows_seats(self):
        response = self.client.get("/book/")
        self.assertContains(response, "Start now")
        self.assertContains(response, 'name="pc" value="%d"' % self.pc1.id)
        self.assertContains(response, "Free")

    def test_books_and_shows_ticket(self):
        response = self.post([self.pc1.id, self.pc2.id])
        group = Booking.objects.first().group
        self.assertRedirects(response, f"/book/{group}/", fetch_redirect_response=False)
        self.assertEqual(Booking.objects.get(pc=self.pc1).start, tomorrow_at(12))
        self.assertEqual(Booking.objects.get(pc=self.pc1).end, tomorrow_at(13, 30))
        ticket = self.client.get(f"/book/{group}/")
        self.assertContains(ticket, "You're booked")
        self.assertContains(ticket, "PC01, PC02")
        self.assertContains(ticket, "₹300")
        self.assertContains(ticket, "₹700")

    def test_double_submit_books_once(self):
        self.post([self.pc1.id])
        response = self.post([self.pc1.id])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PC01 isn&#x27;t free for that time")
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(services.balance_paise(self.customer), 100000 - 15000)

    def test_errors_are_shown_not_crashed(self):
        self.assertContains(self.post([]), "Pick at least one available PC")
        self.assertContains(self.post(["abc"]), "Pick at least one available PC")
        self.assertContains(self.post([self.pc1.id], start="99:99"), "Pick a start time")

    def test_taken_seat_is_marked(self):
        services.book(make_customer("ravi", rupees=500), [self.pc1.id], tomorrow_at(12), 60, timezone.now())
        response = self.client.get(f"/book/?day={self.day}&start=12:00&minutes=60")
        self.assertContains(response, "Taken")
        self.assertContains(response, f'name="pc" value="{self.pc1.id}" disabled')

    def test_other_customers_ticket_is_hidden(self):
        [booking] = services.book(make_customer("ravi", rupees=500), [self.pc1.id], tomorrow_at(12), 60, timezone.now())
        self.assertEqual(self.client.get(f"/book/{booking.group}/").status_code, 404)

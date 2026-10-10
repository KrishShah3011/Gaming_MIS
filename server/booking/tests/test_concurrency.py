import threading

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from booking import services
from booking.models import Booking
from booking.services import BookingError

from .helpers import make_customer, make_pcs, open_24h, tomorrow_at


class ConcurrencyTests(TransactionTestCase):
    """Two requests at the same instant, each on its own database connection."""

    def setUp(self):
        open_24h()
        self.pc1, self.pc2 = make_pcs(2)
        self.now, self.start = timezone.now(), tomorrow_at(12)

    def race(self, *calls):
        barrier, results = threading.Barrier(len(calls)), []

        def run(call):
            try:
                barrier.wait()
                call()
                results.append(True)
            except BookingError:
                results.append(False)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), len(calls), "a thread raised something other than BookingError")
        return results.count(True)

    def test_same_pc_same_time_only_one_wins(self):
        a, b = make_customer("asha", 500), make_customer("ravi", 500)
        wins = self.race(
            lambda: services.book(a, [self.pc1.id], self.start, 60, self.now),
            lambda: services.book(b, [self.pc1.id], self.start, 60, self.now),
        )
        self.assertEqual(wins, 1)
        self.assertEqual(Booking.objects.count(), 1)

    def test_one_wallet_cannot_be_spent_twice(self):
        a = make_customer("asha", 100)
        wins = self.race(
            lambda: services.book(a, [self.pc1.id], self.start, 60, self.now),
            lambda: services.book(a, [self.pc2.id], self.start, 60, self.now),
        )
        self.assertEqual(wins, 1)
        self.assertEqual(services.balance_paise(a), 0)

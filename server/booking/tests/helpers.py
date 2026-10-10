from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from booking.models import Customer, WalletEntry
from status.models import PC, CafeSettings


def make_customer(name="asha", rupees=0, phone="9876543210"):
    user = User.objects.create_user(name, email=f"{name}@example.com", first_name=name.title())
    customer = Customer.objects.create(user=user, phone=phone)
    if rupees:
        WalletEntry.objects.create(customer=customer, amount_paise=rupees * 100, kind=WalletEntry.TOPUP_CASH)
    return customer


def make_pcs(n):
    return [PC.objects.create(hostname=f"PC{i:02}", label=f"PC{i:02}") for i in range(1, n + 1)]


def tomorrow_at(hour, minute=0):
    """Tomorrow at hour:minute café time (aware)."""
    day = timezone.localdate() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def open_24h():
    """Make the café open around the clock, so tests that book "now" pass at any hour."""
    cafe = CafeSettings.load()
    cafe.opens_at = cafe.closes_at = time(0)
    cafe.save()
    return cafe

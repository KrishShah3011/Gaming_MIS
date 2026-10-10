from datetime import date, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from status.models import CafeSettings

from . import rules, services
from .auth import customer_required
from .models import Customer


class PhoneForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["phone"]
        labels = {"phone": "Your mobile number"}
        help_texts = {"phone": "So the café can reach you about a booking. 10 digits, no +91."}
        widgets = {"phone": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "tel-national"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["phone"].required = True


@login_required
def phone(request):
    customer, _ = Customer.objects.get_or_create(user=request.user)
    next_url = request.GET.get("next", "/")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = "/"
    form = PhoneForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(next_url)
    return render(request, "booking/phone.html", {"form": form})


def home(request):
    now, cafe = timezone.now(), CafeSettings.load()
    is_open = rules.opening_period(timezone.localtime(now), cafe.opens_at, cafe.closes_at) is not None
    seats = services.seat_map(now, now + timedelta(minutes=cafe.min_booking_min), now, cafe, start_now=True)
    return render(request, "booking/home.html", {
        "seats": seats,
        "free": sum(seat["free"] for seat in seats),
        "is_open": is_open,
        "offers": services.live_offers(now, cafe),
    })


def _choice(value, options, key):
    """The option whose key(option) equals value, else None."""
    return next((option for option in options if key(option) == value), None)


@customer_required
def book(request):
    now, cafe = timezone.now(), CafeSettings.load()
    local_now = timezone.localtime(now)
    params = request.POST if request.method == "POST" else request.GET
    days = rules.booking_days(local_now, cafe)
    day = _choice(params.get("day"), days, date.isoformat) or days[0]
    can_start_now = day == days[0] and rules.opening_period(local_now, cafe.opens_at, cafe.closes_at) is not None
    starts = rules.start_times(day, local_now, cafe)
    start_now = can_start_now and params.get("start", "now") == "now"
    start = local_now.replace(second=0, microsecond=0) if start_now else (
        _choice(params.get("start"), starts, lambda t: t.strftime("%H:%M"))
        or (None if request.method == "POST" else (starts[0] if starts else None))
    )
    lengths = rules.lengths(cafe)
    minutes = _choice(params.get("minutes"), lengths, str) or cafe.min_booking_min
    picked = [p for p in params.getlist("pc") if p.isdigit()]

    if request.method == "POST":
        if start is None:
            messages.error(request, "Pick a start time.")
        else:
            try:
                bookings = services.book(request.customer, [int(p) for p in picked], start, minutes, now, start_now)
            except services.BookingError as error:
                messages.error(request, str(error))
            else:
                return redirect("ticket", group=bookings[0].group)

    seats = services.seat_map(start, start + timedelta(minutes=minutes), now, cafe, start_now) if start else []
    return render(request, "booking/book.html", {
        "days": days, "day": day, "starts": starts, "start": start, "start_now": start_now,
        "can_start_now": can_start_now, "lengths": lengths, "minutes": minutes,
        "seats": seats, "free_count": sum(seat["free"] for seat in seats), "picked": picked,
        "price": rules.price_paise(cafe.hourly_rate_rupees, minutes),
        "balance": services.balance_paise(request.customer),
    })


@customer_required
def ticket(request, group):
    bookings = list(request.customer.bookings.filter(group=group).select_related("pc").order_by("pc__label", "pc__hostname"))
    if not bookings:
        raise Http404
    return render(request, "booking/ticket.html", {
        "bookings": bookings,
        "first": bookings[0],
        "pc_names": ", ".join(str(b.pc) for b in bookings),
        "paid": sum(services.paid_paise(b) for b in bookings),
        "balance": services.balance_paise(request.customer),
    })

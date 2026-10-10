from datetime import datetime, time, timedelta

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from . import services
from .models import Booking, Customer, Offer, TopUpOrder, WalletEntry
from .templatetags.booking_extras import rupees


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["__str__", "email", "phone", "balance", "created_at"]
    search_fields = ["user__first_name", "user__last_name", "user__email", "phone"]
    fields = ["user", "phone", "created_at", "balance", "wallet"]
    readonly_fields = ["user", "created_at", "balance", "wallet"]

    def has_add_permission(self, request):
        return False  # customers join through Google sign-in

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Email")
    def email(self, obj):
        return obj.user.email

    @admin.display(description="Balance")
    def balance(self, obj):
        # ponytail: one query per row; fine for a café's customer list, annotate if it grows large.
        return rupees(services.balance_paise(obj))

    @admin.display(description="Wallet")
    def wallet(self, obj):
        add, history = reverse("admin:booking_walletentry_add"), reverse("admin:booking_walletentry_changelist")
        return format_html(
            '<a href="{0}?customer={1}&amp;kind=topup_cash">Add cash top-up</a> · '
            '<a href="{0}?customer={1}&amp;kind=correction">Add correction</a> · '
            '<a href="{2}?customer__id__exact={1}">Wallet history</a>',
            add, obj.pk, history,
        )


class WalletEntryForm(forms.ModelForm):
    """Staff add only cash top-ups and corrections, typed in rupees."""

    kind = forms.ChoiceField(choices=[(WalletEntry.TOPUP_CASH, "Cash top-up"), (WalletEntry.CORRECTION, "Correction")])
    rupees = forms.DecimalField(
        max_digits=9, decimal_places=2,
        help_text="Cash top-up: the cash received. Correction: positive adds, negative removes.",
    )
    offer = forms.ModelChoiceField(
        queryset=Offer.objects.none(), required=False,
        help_text="Cash top-ups only. The amount must match the offer.",
    )

    class Meta:
        model = WalletEntry
        fields = ["customer", "kind", "rupees", "offer", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offer"].queryset = Offer.live(timezone.now())

    def clean(self):
        data = super().clean()
        kind, amount, offer = data.get("kind"), data.get("rupees"), data.get("offer")
        if amount is None:
            return data
        if kind == WalletEntry.TOPUP_CASH:
            if amount <= 0:
                self.add_error("rupees", "Enter the cash received.")
            if offer and amount != offer.pay_rupees:
                self.add_error("offer", f"This offer needs exactly ₹{offer.pay_rupees}.")
        else:
            if amount == 0:
                self.add_error("rupees", "Enter an amount other than zero.")
            if offer:
                self.add_error("offer", "Offers apply to cash top-ups only.")
            if not data.get("note"):
                self.add_error("note", "Say why you're correcting the balance.")
        return data


@admin.register(WalletEntry)
class WalletEntryAdmin(admin.ModelAdmin):
    form = WalletEntryForm
    list_display = ["at", "customer", "kind", "amount", "booking", "staff", "note"]
    list_filter = ["kind"]
    search_fields = ["customer__user__email", "customer__user__first_name", "customer__phone", "razorpay_payment_id"]
    autocomplete_fields = ["customer"]

    @admin.display(description="Amount")
    def amount(self, obj):
        return rupees(obj.amount_paise)

    def get_fields(self, request, obj=None):
        if obj is not None:  # viewing an existing entry: show what was recorded
            return ["at", "customer", "kind", "amount_paise", "booking", "razorpay_payment_id", "staff", "note"]
        return super().get_fields(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            kwargs["form"] = forms.ModelForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        data, now = form.cleaned_data, timezone.now()
        obj.amount_paise, obj.staff, obj.at = int(data["rupees"] * 100), request.user, now
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if data.get("offer"):
                WalletEntry.objects.create(customer=obj.customer, amount_paise=data["offer"].bonus_rupees * 100,
                                           kind=WalletEntry.BONUS, staff=request.user, at=now, note=data["offer"].name)

    def has_change_permission(self, request, obj=None):
        return False  # append-only ledger

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ["name", "pay_rupees", "bonus_rupees", "is_active", "valid_until"]
    list_editable = ["is_active"]


class WhenFilter(admin.SimpleListFilter):
    title, parameter_name = "when", "when"

    def lookups(self, request, model_admin):
        return [("now", "Playing now"), ("today", "Today"), ("upcoming", "Upcoming"), ("past", "Past")]

    def queryset(self, request, queryset):
        now = timezone.now()
        day_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
        return {
            "now": lambda: queryset.filter(period__contains=now),
            "today": lambda: queryset.filter(period__overlap=DateTimeTZRange(day_start, day_start + timedelta(days=1))),
            "upcoming": lambda: queryset.filter(period__startswith__gt=now),
            "past": lambda: queryset.filter(period__endswith__lte=now),
        }.get(self.value(), lambda: queryset)()


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["pc", "customer", "start", "end", "status"]
    list_filter = [WhenFilter, "pc"]
    search_fields = ["customer__user__email", "customer__user__first_name", "customer__phone", "pc__label", "pc__hostname"]
    readonly_fields = ["customer", "pc", "period", "group", "created_at", "cancelled_at", "cleared_at", "cleared_by"]
    actions = ["cancel_and_refund"]

    @admin.display(description="Start", ordering="period")
    def start(self, obj):
        return timezone.localtime(obj.start).strftime("%d %b %H:%M")

    @admin.display(description="End")
    def end(self, obj):
        return timezone.localtime(obj.end).strftime("%d %b %H:%M")

    @admin.display(description="Status")
    def status(self, obj):
        if obj.cancelled_at:
            return "Cancelled"
        return "Cleared" if obj.cleared_at else "Booked"

    @admin.action(description="Cancel and refund to wallet")
    def cancel_and_refund(self, request, queryset):
        now, done = timezone.now(), 0
        for booking in queryset:
            try:
                services.cancel(booking, now, by_staff=True)
                done += 1
            except services.BookingError as error:
                self.message_user(request, f"{booking.pc}: {error}", messages.WARNING)
        self.message_user(request, f"Cancelled and refunded {done} booking(s).")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TopUpOrder)
class TopUpOrderAdmin(admin.ModelAdmin):
    list_display = ["razorpay_order_id", "customer", "amount_paise", "bonus_paise", "created_at", "paid_at"]
    search_fields = ["razorpay_order_id", "customer__user__email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

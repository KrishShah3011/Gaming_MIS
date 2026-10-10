from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Customer(models.Model):
    """A website customer. Created on first Google sign-in; name and email come from Google."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer")
    phone = models.CharField(
        max_length=10, blank=True,
        validators=[RegexValidator(r"^[6-9]\d{9}$", "Enter a 10-digit Indian mobile number.")],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.email or self.user.username

    @property
    def first_name(self):
        return self.user.first_name or str(self)


class Booking(models.Model):
    """One PC for one time range. PCs booked together share a `group`."""

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="bookings")
    pc = models.ForeignKey("status.PC", on_delete=models.PROTECT, related_name="bookings")
    period = DateTimeRangeField()  # [start, end)
    group = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            # The database itself refuses two live bookings on one PC at overlapping times.
            ExclusionConstraint(
                name="no_double_booking",
                expressions=[("pc", RangeOperators.EQUAL), ("period", RangeOperators.OVERLAPS)],
                condition=Q(cancelled_at__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.pc} for {self.customer}"

    @property
    def start(self):
        return self.period.lower

    @property
    def end(self):
        return self.period.upper


class WalletEntry(models.Model):
    """One rupee movement. Append-only: the balance is the sum of a customer's entries."""

    TOPUP_ONLINE, TOPUP_CASH, BONUS = "topup_online", "topup_cash", "bonus"
    BOOKING, EXTENSION, REFUND, CORRECTION = "booking", "extension", "refund", "correction"
    KINDS = [
        (TOPUP_ONLINE, "Online top-up"), (TOPUP_CASH, "Cash top-up"), (BONUS, "Offer bonus"),
        (BOOKING, "Booking"), (EXTENSION, "Added time"), (REFUND, "Cancellation refund"),
        (CORRECTION, "Correction"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="wallet_entries")
    amount_paise = models.BigIntegerField()
    kind = models.CharField(max_length=16, choices=KINDS)
    booking = models.ForeignKey(Booking, null=True, blank=True, on_delete=models.PROTECT, related_name="wallet_entries")
    razorpay_payment_id = models.CharField(max_length=64, null=True, blank=True, unique=True)
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name_plural = "wallet entries"


class Offer(models.Model):
    """A top-up pack, e.g. pay ₹500 and get ₹100 bonus. Staff create and switch them in admin."""

    name = models.CharField(max_length=60)
    pay_rupees = models.PositiveIntegerField()
    bonus_rupees = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Leave empty to run until switched off.")

    class Meta:
        ordering = ["pay_rupees"]

    def __str__(self):
        return self.name

    def is_valid(self, now):
        return self.is_active and (self.valid_until is None or now < self.valid_until)

    @classmethod
    def live(cls, now):
        return cls.objects.filter(is_active=True).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=now))


class TopUpOrder(models.Model):
    """A Razorpay order. Amount and bonus are fixed by the server when the order is created."""

    razorpay_order_id = models.CharField(max_length=64, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="topup_orders")
    amount_paise = models.PositiveIntegerField()
    bonus_paise = models.PositiveIntegerField(default=0)
    offer = models.ForeignKey(Offer, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.razorpay_order_id

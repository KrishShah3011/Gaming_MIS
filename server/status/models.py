from datetime import time

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .state import IDLE, IN_USE, OFF, Last


class CafeSettings(models.Model):
    """The single row of tunables, editable in admin (first_milestone.md §6.1)."""

    idle_threshold_s = models.PositiveIntegerField(default=600, validators=[MinValueValidator(60)])
    offline_timeout_s = models.PositiveIntegerField(default=180, validators=[MinValueValidator(60)])
    heartbeat_interval_s = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(30), MaxValueValidator(3600)]
    )
    agents_enabled = models.BooleanField(
        default=True, help_text="Untick to make every agent exit at its next heartbeat (remote off switch)."
    )
    allow_new_pcs = models.BooleanField(
        default=False,
        help_text="Tick while setting up so new PCs can register themselves with their first heartbeat; untick afterwards.",
    )
    # Booking (Milestone 2). Prices are whole rupees; the wallet stores paise.
    hourly_rate_rupees = models.PositiveIntegerField(default=100, validators=[MinValueValidator(1)])
    booking_step_min = models.PositiveSmallIntegerField(
        default=30, choices=[(15, "15 minutes"), (30, "30 minutes")],
        help_text="Start times and lengths move in steps of this size.",
    )
    min_booking_min = models.PositiveSmallIntegerField(default=60, validators=[MinValueValidator(15)])
    cancel_cutoff_min = models.PositiveIntegerField(
        default=120, help_text="Customers can cancel until this many minutes before the start."
    )
    opens_at = models.TimeField(default=time(10, 0))
    closes_at = models.TimeField(
        default=time(23, 0),
        help_text="Earlier than the opening time means the café closes after midnight. Same as opening means open 24 hours.",
    )
    advance_days = models.PositiveSmallIntegerField(default=7, validators=[MinValueValidator(1)])
    # Shown on the website's Contact and policy pages (Razorpay requires them).
    cafe_name = models.CharField(max_length=80, default="Gaming Café")
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "café settings"

    def __str__(self):
        return "Café settings"

    def clean(self):
        errors = {}
        timeout, interval = self.offline_timeout_s, self.heartbeat_interval_s
        if None not in (timeout, interval) and timeout < 2 * interval:
            errors["offline_timeout_s"] = "Must be at least twice the heartbeat interval, or PCs will flicker to Off."
        step, min_len = self.booking_step_min, self.min_booking_min
        if None not in (step, min_len) and min_len % step:
            errors["min_booking_min"] = "Must be a whole number of booking steps."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings


class PC(models.Model):
    STATES = [(IN_USE, "In use"), (IDLE, "Idle"), (OFF, "Off")]

    hostname = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64, blank=True)
    mac = models.CharField(max_length=17, blank=True)
    is_active = models.BooleanField(default=True, help_text="Untick to hide from the dashboard.")
    # Live fields, as of the last heartbeat.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_event = models.CharField(max_length=16, blank=True)
    idle_s_at_last_seen = models.PositiveIntegerField(default=0)
    boot_id = models.CharField(max_length=64, blank=True)
    agent_version = models.CharField(max_length=32, blank=True)
    state = models.CharField(max_length=8, choices=STATES, default=OFF)
    state_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label", "hostname"]
        verbose_name = "PC"

    def __str__(self):
        return self.label or self.hostname

    def last(self) -> Last:
        return Last(self.last_seen_at, self.last_event, self.idle_s_at_last_seen, self.state, self.state_since)


class StateChange(models.Model):
    """One row per state change. Future analytics (M4) are built on this; it can't be back-filled."""

    pc = models.ForeignKey(PC, on_delete=models.CASCADE, related_name="state_changes")
    from_state = models.CharField(max_length=8, choices=PC.STATES)
    to_state = models.CharField(max_length=8, choices=PC.STATES)
    at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["pc", "at"])]
        ordering = ["-at"]

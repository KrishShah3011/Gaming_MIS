from django.contrib import admin

from .models import PC, CafeSettings, StateChange


@admin.register(CafeSettings)
class CafeSettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ("PC status", {"fields": [
            "idle_threshold_s", "offline_timeout_s", "heartbeat_interval_s", "agents_enabled", "allow_new_pcs",
        ]}),
        ("Booking", {"fields": [
            "hourly_rate_rupees", "booking_step_min", "min_booking_min", "cancel_cutoff_min",
            "opens_at", "closes_at", "advance_days",
        ]}),
        ("Café details (shown on the website)", {"fields": ["cafe_name", "contact_phone", "contact_email", "address"]}),
    ]

    def has_add_permission(self, request):
        return not CafeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PC)
class PCAdmin(admin.ModelAdmin):
    list_display = ["hostname", "label", "state", "state_since", "last_seen_at", "agent_version", "is_active"]
    list_editable = ["label", "is_active"]
    readonly_fields = [
        "hostname", "mac", "last_seen_at", "last_event", "idle_s_at_last_seen",
        "boot_id", "agent_version", "state", "state_since", "created_at",
    ]

    def has_add_permission(self, request):
        return False  # PCs register themselves with their first heartbeat


@admin.register(StateChange)
class StateChangeAdmin(admin.ModelAdmin):
    list_display = ["at", "pc", "from_state", "to_state"]
    list_filter = ["pc", "to_state"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin

from .models import PC, CafeSettings, StateChange


@admin.register(CafeSettings)
class CafeSettingsAdmin(admin.ModelAdmin):
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

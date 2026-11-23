from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from datalayer.models import (
    Advisor,
    Conversation,
    Execution,
    Message,
    Notification,
    Property,
    Prospect,
    ProspectEvent,
    User,
)


@admin.register(User)
class MaiaUserAdmin(UserAdmin):
    search_fields = ("email",)
    ordering = ("email",)
    list_display = ("email", "is_staff", "is_active")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Permisos",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "is_staff")}),
    )


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "operation", "municipality", "price", "published")
    list_filter = ("operation", "published", "municipality")
    readonly_fields = (
        "normalized_zone",
        "created_at",
        "updated_at",
        "physical_property",
        "commercialization_round",
    )

    def has_change_permission(self, request, obj=None):
        if obj and obj.closing_periods.filter(period=obj.commercialization_round).exists():
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.closings.exists() or obj.closing_periods.exists()):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "status",
        "input_tokens",
        "output_tokens",
        "elapsed_ms",
        "created_at",
    )
    readonly_fields = tuple(field.name for field in Execution._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(Advisor)
admin.site.register(Prospect)
admin.site.register(Notification)
admin.site.register(ProspectEvent)

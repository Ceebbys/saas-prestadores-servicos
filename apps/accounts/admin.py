from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Empresa, EmpresaEmailConfig, Membership, User


@admin.register(EmpresaEmailConfig)
class EmpresaEmailConfigAdmin(admin.ModelAdmin):
    list_display = ("empresa", "from_email", "host", "port", "is_active",
                    "last_tested_at", "last_test_ok")
    list_filter = ("is_active", "use_tls", "use_ssl")
    readonly_fields = ("password_encrypted", "last_tested_at",
                       "last_test_ok", "last_test_error")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff")
    search_fields = ("email", "full_name")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Informações", {"fields": ("full_name", "phone", "avatar", "active_empresa")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2")}),
    )


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("name", "segment", "is_active", "created_at")
    list_filter = ("segment", "is_active")
    search_fields = ("name", "document")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "empresa", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("user__full_name", "empresa__name")

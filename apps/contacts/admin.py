from django.contrib import admin

from .models import Contato


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = (
        "name", "cpf_cnpj", "phone", "email", "company",
        "source", "is_active", "empresa", "created_at",
    )
    list_filter = ("is_active", "source", "empresa")
    search_fields = ("name", "cpf_cnpj_normalized", "phone", "whatsapp", "email", "company")
    list_select_related = ("empresa",)
    readonly_fields = ("cpf_cnpj_normalized", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("empresa", "name", "is_active", "source")}),
        ("Documento", {"fields": ("cpf_cnpj", "cpf_cnpj_normalized")}),
        ("Contato", {"fields": ("phone", "whatsapp", "email")}),
        ("Detalhes", {"fields": ("company", "notes")}),
        ("Auditoria", {"fields": ("created_at", "updated_at")}),
    )

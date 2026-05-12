from django import forms

from apps.core.document_render.image_validation import (
    ALLOWED_DOCUMENT_IMAGE_EXTS as ALLOWED_HEADER_IMAGE_EXTS,  # noqa: F401
    MAX_DOCUMENT_IMAGE_BYTES as MAX_HEADER_IMAGE_BYTES,  # noqa: F401
    validate_document_image as _validate_header_image,
)
from apps.core.document_render.sanitizer import sanitize_rich_html as sanitize_proposal_html
from apps.core.forms import TailwindFormMixin
from apps.proposals.models import (
    Proposal,
    ProposalItem,
    ProposalTemplate,
    ProposalTemplateItem,
)


class _RichTextSanitizingMixin:
    """Aplica `sanitize_proposal_html` em campos rich-text declarados em RICH_TEXT_FIELDS."""

    RICH_TEXT_FIELDS: tuple[str, ...] = ()

    def _sanitize_rich(self, field_name: str) -> str:
        return sanitize_proposal_html(self.cleaned_data.get(field_name, "") or "")


class ProposalForm(_RichTextSanitizingMixin, TailwindFormMixin, forms.ModelForm):
    RICH_TEXT_FIELDS = ("introduction", "body", "terms", "footer_content")

    class Meta:
        model = Proposal
        fields = [
            "title",
            "lead",
            "opportunity",
            "servico",
            "template",
            "header_image",
            "use_template_header_image",
            "introduction",
            "body",
            "terms",
            "footer_image",
            "footer_content",
            "discount_percent",
            "valid_until",
            "payment_methods",  # RV05 #5 — múltiplas formas
            "payment_method",  # legado: dual-read durante 1 release
            "is_installment",
            "installment_count",
        ]
        widgets = {
            "valid_until": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
            "introduction": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "body": forms.Textarea(attrs={"rows": 8, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "payment_methods": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["lead"].queryset = self.fields["lead"].queryset.filter(
                empresa=empresa
            )
            self.fields["opportunity"].queryset = self.fields[
                "opportunity"
            ].queryset.filter(empresa=empresa)
            self.fields["template"].queryset = self.fields[
                "template"
            ].queryset.filter(empresa=empresa)
            from apps.operations.models import ServiceType

            self.fields["servico"].queryset = ServiceType.objects.filter(
                empresa=empresa, is_active=True,
            )
            self.fields["servico"].required = False
            self.fields["servico"].empty_label = "—"
        # M2M de formas de pagamento — apenas as ativas
        self.fields["payment_methods"].queryset = (
            self.fields["payment_methods"].queryset.filter(is_active=True)
        )
        self.fields["payment_methods"].required = False

    def clean_header_image(self):
        return _validate_header_image(self.cleaned_data.get("header_image"))

    def clean_footer_image(self):
        return _validate_header_image(self.cleaned_data.get("footer_image"))

    def clean_introduction(self):
        return self._sanitize_rich("introduction")

    def clean_body(self):
        return self._sanitize_rich("body")

    def clean_terms(self):
        return self._sanitize_rich("terms")

    def clean_footer_content(self):
        return self._sanitize_rich("footer_content")


class ProposalItemForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ProposalItem
        fields = [
            "description",
            "details",
            "quantity",
            "unit",
            "unit_price",
        ]


class ProposalTemplateForm(
    _RichTextSanitizingMixin, TailwindFormMixin, forms.ModelForm
):
    RICH_TEXT_FIELDS = (
        "introduction", "terms", "header_content", "footer_content",
    )

    default_payment_method = forms.ChoiceField(
        label="Forma de pagamento padrão",
        required=False,
        choices=[("", "---------")] + list(Proposal.PaymentMethod.choices),
    )

    class Meta:
        model = ProposalTemplate
        fields = [
            "name",
            "is_default",
            "header_image",
            "header_content",
            "footer_image",  # RV05-F — simetria com header
            "footer_content",
            "introduction",
            "terms",
            "default_payment_method",
            "default_is_installment",
            "default_installment_count",
        ]
        widgets = {
            "introduction": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "header_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
        }

    def clean_header_image(self):
        return _validate_header_image(self.cleaned_data.get("header_image"))

    def clean_footer_image(self):
        # RV05-F — mesma validação do header
        return _validate_header_image(self.cleaned_data.get("footer_image"))

    def clean_introduction(self):
        return self._sanitize_rich("introduction")

    def clean_terms(self):
        return self._sanitize_rich("terms")

    def clean_header_content(self):
        return self._sanitize_rich("header_content")

    def clean_footer_content(self):
        return self._sanitize_rich("footer_content")


class ProposalTemplateItemForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ProposalTemplateItem
        fields = [
            "description",
            "details",
            "quantity",
            "unit",
            "unit_price",
        ]

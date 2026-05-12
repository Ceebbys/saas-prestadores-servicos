from django import forms

from apps.contracts.models import Contract, ContractTemplate
from apps.core.document_render.image_validation import validate_document_image
from apps.core.document_render.sanitizer import sanitize_rich_html
from apps.core.forms import TailwindFormMixin


class _ContractRichTextMixin:
    """Sanitiza todos os campos rich-text do Contract via core sanitizer."""

    RICH_TEXT_FIELDS: tuple[str, ...] = (
        "header_content", "introduction", "body", "terms", "footer_content",
    )

    def _sanitize_rich(self, field_name: str) -> str:
        return sanitize_rich_html(self.cleaned_data.get(field_name, "") or "")

    def clean_header_image(self):
        return validate_document_image(self.cleaned_data.get("header_image"))

    def clean_footer_image(self):
        return validate_document_image(self.cleaned_data.get("footer_image"))

    def clean_header_content(self):
        return self._sanitize_rich("header_content")

    def clean_introduction(self):
        return self._sanitize_rich("introduction")

    def clean_body(self):
        return self._sanitize_rich("body")

    def clean_terms(self):
        return self._sanitize_rich("terms")

    def clean_footer_content(self):
        return self._sanitize_rich("footer_content")


class ContractForm(_ContractRichTextMixin, TailwindFormMixin, forms.ModelForm):
    """Form principal do Contract — agora com rich-text + imagens (RV05 #11)."""

    class Meta:
        model = Contract
        fields = [
            "title", "lead", "proposal", "template",
            # Cabeçalho
            "header_image", "header_content",
            # Conteúdo
            "introduction", "body", "terms",
            # Rodapé
            "footer_image", "footer_content",
            # Comerciais
            "value", "start_date", "end_date", "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d",
            ),
            "end_date": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d",
            ),
            "header_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
            "introduction": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "body": forms.Textarea(attrs={"rows": 10, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields["lead"].queryset = self.fields["lead"].queryset.filter(
                empresa=empresa
            )
            self.fields["proposal"].queryset = self.fields[
                "proposal"
            ].queryset.filter(empresa=empresa)
            self.fields["template"].queryset = self.fields[
                "template"
            ].queryset.filter(empresa=empresa)


class ContractTemplateForm(_ContractRichTextMixin, TailwindFormMixin, forms.ModelForm):
    """Form do ContractTemplate — também rich-text + imagens."""

    class Meta:
        model = ContractTemplate
        fields = [
            "name", "is_default",
            "header_image", "header_content",
            "introduction", "body", "terms",
            "footer_image", "footer_content",
        ]
        widgets = {
            "header_content": forms.Textarea(attrs={"rows": 3, "data-rich-text": "true"}),
            "introduction": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
            "body": forms.Textarea(attrs={"rows": 10, "data-rich-text": "true"}),
            "terms": forms.Textarea(attrs={"rows": 5, "data-rich-text": "true"}),
            "footer_content": forms.Textarea(attrs={"rows": 4, "data-rich-text": "true"}),
        }

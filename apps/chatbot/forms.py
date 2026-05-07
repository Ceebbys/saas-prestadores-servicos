from django import forms

from apps.core.forms import TailwindFormMixin

from .models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep


class ChatbotFlowForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotFlow
        fields = [
            "name",
            "channel",
            "description",
            "welcome_message",
            "fallback_message",
            "is_active",
            "trigger_type",
            "trigger_keywords",
            "inactivity_minutes",
            "priority",
            "cooldown_minutes",
            "exclusive",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "welcome_message": forms.Textarea(attrs={"rows": 3}),
            "fallback_message": forms.Textarea(attrs={"rows": 2}),
            "trigger_keywords": forms.TextInput(attrs={
                "placeholder": "ex.: orçamento, preço, valores",
            }),
            "inactivity_minutes": forms.NumberInput(attrs={
                "placeholder": "180 = 3h, 1440 = 24h",
                "min": 1,
            }),
        }


class ChatbotStepForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotStep
        fields = [
            "order",
            "question_text",
            "step_type",
            "lead_field_mapping",
            "is_required",
            "is_final",
        ]
        widgets = {
            "question_text": forms.Textarea(attrs={"rows": 2}),
        }


class ChatbotChoiceForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotChoice
        fields = ["text", "order", "next_step"]

    def __init__(self, *args, flow=None, exclude_step=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ChatbotStep.objects.none()
        if flow:
            qs = ChatbotStep.objects.filter(flow=flow).order_by("order")
            if exclude_step is not None:
                qs = qs.exclude(pk=exclude_step.pk)
        self.fields["next_step"].queryset = qs
        self.fields["next_step"].required = False
        self.fields["next_step"].empty_label = "(linear — próximo na ordem)"


# Formset usado pelo builder para editar todas as choices de uma etapa de uma vez.
# fk_name="step" é necessário porque ChatbotChoice tem duas FKs para ChatbotStep
# (`step` = pai; `next_step` = destino da ramificação).
ChatbotChoiceFormSet = forms.inlineformset_factory(
    ChatbotStep,
    ChatbotChoice,
    form=ChatbotChoiceForm,
    fk_name="step",
    fields=["text", "order", "next_step"],
    extra=1,
    can_delete=True,
)


class ChatbotActionForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotAction
        fields = ["trigger", "action_type"]

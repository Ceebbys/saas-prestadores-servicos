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
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "welcome_message": forms.Textarea(attrs={"rows": 3}),
            "fallback_message": forms.Textarea(attrs={"rows": 2}),
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
        ]
        widgets = {
            "question_text": forms.Textarea(attrs={"rows": 2}),
        }


class ChatbotChoiceForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotChoice
        fields = ["text", "order", "next_step"]

    def __init__(self, *args, flow=None, **kwargs):
        super().__init__(*args, **kwargs)
        if flow:
            self.fields["next_step"].queryset = ChatbotStep.objects.filter(
                flow=flow
            )
        self.fields["next_step"].required = False


class ChatbotActionForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotAction
        fields = ["trigger", "action_type"]

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
            "send_completion_message",
            "completion_message",
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
            "completion_message": forms.Textarea(attrs={"rows": 3}),
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
            "parent",
            "subordem",
            "question_text",
            "step_type",
            "lead_field_mapping",
            "is_required",
            "is_final",
        ]
        widgets = {
            "question_text": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, flow=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Restringe seleção de "pai" aos passos do mesmo fluxo, excluindo o próprio.
        qs = ChatbotStep.objects.none()
        if flow is not None:
            qs = ChatbotStep.objects.filter(flow=flow)
            if self.instance and self.instance.pk:
                # Exclui o próprio e sua subárvore para evitar ciclo.
                descendant_ids = self._collect_descendants(self.instance)
                qs = qs.exclude(pk__in=descendant_ids)
        elif self.instance and self.instance.pk and self.instance.flow_id:
            qs = ChatbotStep.objects.filter(flow=self.instance.flow)
            descendant_ids = self._collect_descendants(self.instance)
            qs = qs.exclude(pk__in=descendant_ids)
        self.fields["parent"].queryset = qs.order_by("codigo_hierarquico", "order")
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "(sem pai — etapa raiz)"

    @staticmethod
    def _collect_descendants(step):
        """Retorna {pk, ...} de step e todos os descendentes (BFS)."""
        ids = {step.pk}
        frontier = [step.pk]
        while frontier:
            children = list(
                ChatbotStep.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
            )
            new = [pk for pk in children if pk not in ids]
            ids.update(new)
            frontier = new
        return ids


class ChatbotChoiceForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotChoice
        fields = ["text", "order", "next_step", "servico"]

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

        # Restringe serviços à empresa do flow (multi-tenant).
        from apps.operations.models import ServiceType
        servico_qs = ServiceType.objects.none()
        if flow is not None:
            servico_qs = ServiceType.objects.filter(
                empresa=flow.empresa, is_active=True,
            ).order_by("name")
        self.fields["servico"].queryset = servico_qs
        self.fields["servico"].required = False
        self.fields["servico"].empty_label = "— Sem serviço associado —"


# Formset usado pelo builder para editar todas as choices de uma etapa de uma vez.
# fk_name="step" é necessário porque ChatbotChoice tem duas FKs para ChatbotStep
# (`step` = pai; `next_step` = destino da ramificação).
ChatbotChoiceFormSet = forms.inlineformset_factory(
    ChatbotStep,
    ChatbotChoice,
    form=ChatbotChoiceForm,
    fk_name="step",
    fields=["text", "order", "next_step", "servico"],
    extra=1,
    can_delete=True,
)


class ChatbotActionForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = ChatbotAction
        fields = ["trigger", "action_type"]

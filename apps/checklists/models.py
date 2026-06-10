"""RV08 (2.1/2.2) — Checklists múltiplos estilo Trello, reutilizáveis.

Um mesmo modelo serve a qualquer "dono" via relação genérica (content_type +
object_id): hoje os cards da Pipeline (``crm.Opportunity``) e as Ordens de
Serviço (``operations.WorkOrder``). Cada dono pode ter VÁRIOS checklists
nomeados, e cada checklist tem seus próprios itens.

O checklist fica associado à execução do serviço (não ao Lead), conforme o
pedido do RV08 — por isso vive em um app próprio e não em ``crm``.
"""
from __future__ import annotations

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.core.models import TenantOwnedModel, TimestampedModel


class Checklist(TenantOwnedModel):
    """Um checklist nomeado pertencente a uma entidade (Opportunity, WorkOrder…)."""

    name = models.CharField("Nome", max_length=120, default="Checklist")
    order = models.PositiveIntegerField("Ordem", default=0)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    owner = GenericForeignKey("content_type", "object_id")

    class Meta:
        verbose_name = "Checklist"
        verbose_name_plural = "Checklists"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["empresa", "content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def total(self) -> int:
        return self.items.count()

    @property
    def completed(self) -> int:
        return self.items.filter(is_completed=True).count()

    @property
    def progress_pct(self) -> int:
        total = self.total
        return int(self.completed / total * 100) if total else 0


class ChecklistItem(TimestampedModel):
    """Item de um :class:`Checklist`. Alcança o tenant via ``checklist.empresa``."""

    checklist = models.ForeignKey(
        Checklist,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Checklist",
    )
    description = models.CharField("Descrição", max_length=500)
    is_completed = models.BooleanField("Concluído", default=False)
    completed_at = models.DateTimeField("Concluído em", null=True, blank=True)
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item de Checklist"
        verbose_name_plural = "Itens de Checklist"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.description

    def toggle(self):
        """Alterna a conclusão, mantendo ``completed_at`` coerente."""
        if self.is_completed:
            self.is_completed = False
            self.completed_at = None
        else:
            self.is_completed = True
            self.completed_at = timezone.now()
        self.save(update_fields=["is_completed", "completed_at", "updated_at"])

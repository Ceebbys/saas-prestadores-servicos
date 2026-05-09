from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    """Abstract base model with created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantOwnedModel(TimestampedModel):
    """Abstract model that belongs to an Empresa (tenant)."""

    empresa = models.ForeignKey(
        "accounts.Empresa",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet que permite soft-delete e restauração."""

    def delete(self):
        return self.update(deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)

    def restore(self):
        return self.update(deleted_at=None)


class SoftDeleteManager(models.Manager):
    """Manager default que esconde rows soft-deleted."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(
            deleted_at__isnull=True,
        )


class SoftDeleteAllManager(models.Manager):
    """Manager que retorna TUDO (incluindo soft-deleted) — para listagens admin/lixeira."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeletableModel(models.Model):
    """Abstract mixin para soft-delete.

    Uso:
        class MeuModelo(SoftDeletableModel, TenantOwnedModel):
            ...

    Comportamento:
    - `Modelo.objects` (default) esconde soft-deleted.
    - `Modelo.all_objects` retorna tudo (lixeira, admin).
    - `instance.delete()` faz soft-delete por padrão.
    - `instance.hard_delete()` força exclusão real.
    - `instance.restore()` restaura.
    - `Modelo.objects.deleted()` lista lixeira.
    """

    deleted_at = models.DateTimeField(
        "Excluído em", null=True, blank=True, db_index=True, editable=False,
    )

    objects = SoftDeleteManager()
    all_objects = SoftDeleteAllManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, hard: bool = False):
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])
        return (1, {self._meta.label: 1})

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

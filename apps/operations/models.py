from urllib.parse import quote

from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel
from apps.core.utils import generate_number


class ServiceType(TenantOwnedModel):
    """Tipo de serviço oferecido pela empresa."""

    name = models.CharField("Nome", max_length=255)
    description = models.TextField("Descrição", blank=True)
    estimated_duration_hours = models.DecimalField(
        "Duração estimada (horas)",
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Tipo de Serviço"
        verbose_name_plural = "Tipos de Serviço"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChecklistTemplate(TenantOwnedModel):
    """Template de checklist reutilizável."""

    name = models.CharField("Nome", max_length=255)

    class Meta:
        verbose_name = "Template de Checklist"
        verbose_name_plural = "Templates de Checklist"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChecklistItem(TimestampedModel):
    """Item de um template de checklist."""

    template = models.ForeignKey(
        ChecklistTemplate,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Template",
    )
    description = models.CharField("Descrição", max_length=500)
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item do Checklist"
        verbose_name_plural = "Itens do Checklist"
        ordering = ["order"]

    def __str__(self):
        return self.description


class Team(TenantOwnedModel):
    """Equipe de trabalho da empresa."""

    name = models.CharField("Nome", max_length=100)
    description = models.TextField("Descrição", blank=True)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_teams",
        verbose_name="Líder",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TeamMember",
        related_name="teams",
        blank=True,
        verbose_name="Membros",
    )
    color = models.CharField(
        "Cor",
        max_length=20,
        default="indigo",
        help_text="Cor para exibição no calendário.",
    )
    is_active = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Equipe"
        verbose_name_plural = "Equipes"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.team_members.filter(is_active=True).count()


class TeamMember(TimestampedModel):
    """Associação de um membro a uma equipe."""

    class Role(models.TextChoices):
        MEMBER = "member", "Membro"
        LEADER = "leader", "Líder"

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name="Equipe",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
        verbose_name="Usuário",
    )
    role = models.CharField(
        "Papel",
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Membro da Equipe"
        verbose_name_plural = "Membros da Equipe"
        unique_together = ("team", "user")
        ordering = ["-role", "user__full_name"]

    def __str__(self):
        return f"{self.user.full_name} ({self.team.name})"


class WorkOrder(TenantOwnedModel):
    """Ordem de serviço vinculada a propostas e contratos."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SCHEDULED = "scheduled", "Agendada"
        IN_PROGRESS = "in_progress", "Em Andamento"
        ON_HOLD = "on_hold", "Pausada"
        COMPLETED = "completed", "Concluída"
        CANCELLED = "cancelled", "Cancelada"

    class Priority(models.TextChoices):
        LOW = "low", "Baixa"
        MEDIUM = "medium", "Média"
        HIGH = "high", "Alta"

    number = models.CharField("Número", max_length=50, db_index=True)
    title = models.CharField("Título", max_length=255)
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="Lead",
    )
    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="Proposta",
    )
    contract = models.ForeignKey(
        "contracts.Contract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="Contrato",
    )
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="Tipo de Serviço",
    )
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    priority = models.CharField(
        "Prioridade",
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    description = models.TextField("Descrição", blank=True)
    scheduled_date = models.DateField("Data agendada", null=True, blank=True)
    scheduled_time = models.TimeField("Horário agendado", null=True, blank=True)
    completed_at = models.DateTimeField("Concluída em", null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_work_orders",
        verbose_name="Responsável",
    )
    assigned_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_orders",
        verbose_name="Equipe",
    )
    location = models.TextField("Local", blank=True)
    google_maps_url = models.URLField(
        "Link Google Maps", max_length=500, blank=True
    )
    cloud_storage_links = models.JSONField(
        "Links de Arquivos",
        default=list,
        blank=True,
        help_text='Lista de links (Google Drive, Dropbox, etc.)',
    )
    notes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Ordem de Serviço"
        verbose_name_plural = "Ordens de Serviço"
        ordering = ["-scheduled_date", "-created_at"]

    def __str__(self):
        return f"{self.number} - {self.title}"

    @property
    def google_maps_auto_url(self):
        """Gera URL do Google Maps a partir do endereço quando não há link manual."""
        if self.location and self.location.strip():
            return f"https://www.google.com/maps/search/?api=1&query={quote(self.location.strip())}"
        return ""

    @property
    def maps_url(self):
        """Retorna link Maps manual ou auto-gerado."""
        return self.google_maps_url or self.google_maps_auto_url

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_number(self.empresa, "OS", WorkOrder)
        super().save(*args, **kwargs)


class WorkOrderChecklist(TimestampedModel):
    """Item de checklist de uma ordem de serviço."""

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="checklist_items",
        verbose_name="Ordem de Serviço",
    )
    description = models.CharField("Descrição", max_length=500)
    is_completed = models.BooleanField("Concluído", default=False)
    completed_at = models.DateTimeField("Concluído em", null=True, blank=True)
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Item do Checklist da OS"
        verbose_name_plural = "Itens do Checklist da OS"
        ordering = ["order"]

    def __str__(self):
        return self.description

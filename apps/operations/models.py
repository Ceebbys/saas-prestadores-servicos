from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel
from apps.core.utils import generate_number


class ServiceType(TenantOwnedModel):
    """Serviço pré-fixado da empresa.

    Catálogo de serviços padronizados que alimentam:
    - Chatbot (opção do cliente vincula a um serviço)
    - Lead (categoria + sugestões automáticas)
    - Proposta (preço, descrição, modelo, prazo)
    - Contrato (modelo padrão)
    - Pipeline (etapa inicial sugerida)
    """

    name = models.CharField("Nome", max_length=255)
    code = models.CharField(
        "Código",
        max_length=40,
        blank=True,
        db_index=True,
        help_text="Código curto opcional (ex.: TOPO-001).",
    )
    category = models.CharField(
        "Categoria",
        max_length=80,
        blank=True,
        db_index=True,
    )
    description = models.TextField("Descrição interna", blank=True)
    default_description = models.TextField(
        "Descrição padrão (rich)",
        blank=True,
        help_text="HTML rich-text. Usado em propostas/leads como sugestão.",
    )
    default_price = models.DecimalField(
        "Preço padrão",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    default_prazo_dias = models.PositiveIntegerField(
        "Prazo estimado (dias)",
        null=True,
        blank=True,
    )
    estimated_duration_hours = models.DecimalField(
        "Duração estimada (horas)",
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
    )
    default_proposal_template = models.ForeignKey(
        "proposals.ProposalTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_service_types",
        verbose_name="Modelo de proposta padrão",
    )
    default_contract_template = models.ForeignKey(
        "contracts.ContractTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_service_types",
        verbose_name="Modelo de contrato padrão",
    )
    default_pipeline = models.ForeignKey(
        "crm.Pipeline",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_service_types",
        verbose_name="Pipeline padrão",
    )
    default_stage = models.ForeignKey(
        "crm.PipelineStage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_service_types",
        verbose_name="Etapa padrão",
    )
    tags = models.CharField(
        "Tags",
        max_length=255,
        blank=True,
        help_text="Separadas por vírgula (ex.: topografia, regularização).",
    )
    internal_notes = models.TextField("Observações internas", blank=True)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Serviço Cadastrado"
        verbose_name_plural = "Serviços Cadastrados"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["empresa", "category"]),
            models.Index(fields=["empresa", "is_active"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.default_stage_id and self.default_pipeline_id:
            if self.default_stage.pipeline_id != self.default_pipeline_id:
                raise ValidationError({
                    "default_stage": (
                        "A etapa precisa pertencer ao pipeline selecionado."
                    ),
                })

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


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
    # RV10 — Cliente pediu: "colocar na os previsão de término. pq ai vai
    # para o calendário e ocara vê quem ta garrado ou não. AI a previsão
    # se for de serviço cadastrado puxa de lá mas pode ficar editavel".
    # Auto-populado pelo form: scheduled_date + service_type.default_prazo_dias.
    expected_end_date = models.DateField(
        "Previsão de término", null=True, blank=True,
        help_text=(
            "Quando a OS deve terminar. Calculado a partir do prazo do "
            "serviço cadastrado, mas pode ser editado."
        ),
    )
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


class JobRole(TenantOwnedModel):
    """RV07 (3.1) — Função/cargo do colaborador (ex.: Topógrafo, Engenheiro).

    Usado como escopo de tarifa horária (HourRate) e atribuível ao Membership.
    """

    name = models.CharField("Função / Cargo", max_length=100)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Função / Cargo"
        verbose_name_plural = "Funções / Cargos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "name"], name="uniq_jobrole_name_per_empresa",
            ),
        ]

    def __str__(self):
        return self.name


class HourRate(TenantOwnedModel):
    """RV07 (3.1) — Tarifa horária configurável por escopo.

    Três escopos (conforme o PDF):
      - TEAM      → valor hora da equipe (padrão da empresa). Único por empresa.
      - USER      → valor hora do responsável (por usuário).
      - JOB_ROLE  → valor hora por função/cargo.
    """

    class Scope(models.TextChoices):
        TEAM = "team", "Equipe (padrão da empresa)"
        USER = "user", "Responsável (por usuário)"
        JOB_ROLE = "job_role", "Função / Cargo"

    scope = models.CharField("Escopo", max_length=10, choices=Scope.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, null=True, blank=True,
        related_name="hour_rates", verbose_name="Responsável",
    )
    job_role = models.ForeignKey(
        JobRole,
        on_delete=models.CASCADE, null=True, blank=True,
        related_name="hour_rates", verbose_name="Função / Cargo",
    )
    hourly_value = models.DecimalField(
        "Valor por hora (R$)", max_digits=12, decimal_places=2,
    )
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Valor Hora"
        verbose_name_plural = "Valores Hora"
        ordering = ["scope", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"], condition=models.Q(scope="team"),
                name="uniq_team_rate_per_empresa",
            ),
            models.UniqueConstraint(
                fields=["empresa", "user"], condition=models.Q(scope="user"),
                name="uniq_user_rate_per_empresa",
            ),
            models.UniqueConstraint(
                fields=["empresa", "job_role"], condition=models.Q(scope="job_role"),
                name="uniq_jobrole_rate_per_empresa",
            ),
        ]

    def clean(self):
        if self.scope == self.Scope.USER and not self.user_id:
            raise ValidationError({"user": "Selecione o responsável."})
        if self.scope == self.Scope.JOB_ROLE and not self.job_role_id:
            raise ValidationError({"job_role": "Selecione a função/cargo."})
        if self.scope == self.Scope.TEAM:
            self.user = None
            self.job_role = None

    def __str__(self):
        return f"{self.get_scope_display()} — R$ {self.hourly_value}"


class WorkOrderTimeLog(TimestampedModel):
    """RV07 (3.1) — Apontamento de horas de uma Ordem de Serviço.

    Estilo ClickUp/Monday: cronômetro (start/stop por intervalo) + lançamento
    manual + histórico. Filho de WorkOrder (alcança o tenant via
    work_order.empresa, igual ao WorkOrderChecklist).

    Pausar = encerrar o intervalo atual; Retomar = iniciar um novo. O total é a
    soma dos intervalos — representação limpa e com histórico fiel.
    """

    class Source(models.TextChoices):
        TIMER = "timer", "Cronômetro"
        MANUAL = "manual", "Manual"

    work_order = models.ForeignKey(
        WorkOrder,
        on_delete=models.CASCADE,
        related_name="time_logs",
        verbose_name="Ordem de Serviço",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,  # preserva histórico se o usuário for removido
        null=True, blank=True,
        related_name="work_order_time_logs",
        verbose_name="Colaborador",
    )
    source = models.CharField(
        "Origem", max_length=10, choices=Source.choices, default=Source.TIMER,
    )
    started_at = models.DateTimeField("Início")
    ended_at = models.DateTimeField("Fim", null=True, blank=True)  # null = rodando
    duration_seconds = models.PositiveIntegerField(
        "Duração (s)", default=0,
        help_text="Calculado ao parar o cronômetro ou no lançamento manual.",
    )
    is_billable = models.BooleanField("Faturável", default=True)
    rate_applied = models.DecimalField(
        "Valor hora aplicado", max_digits=12, decimal_places=2,
        null=True, blank=True,
    )
    rate_source = models.CharField(
        "Origem da tarifa", max_length=20, blank=True,
        help_text="responsavel | funcao | equipe | (vazio = sem tarifa)",
    )
    notes = models.CharField("Observações", max_length=500, blank=True)

    class Meta:
        verbose_name = "Apontamento de Horas"
        verbose_name_plural = "Apontamentos de Horas"
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_order", "user"],
                condition=models.Q(ended_at__isnull=True),
                name="uniq_running_timer_per_user_wo",
            ),
            # Pente fino: NULLs são distintos em índice único, então a constraint
            # acima não cobre user=NULL (caso o colaborador seja removido com o
            # cronômetro rodando → SET_NULL). Esta garante no máx. 1 cronômetro
            # rodando sem usuário por OS.
            models.UniqueConstraint(
                fields=["work_order"],
                condition=models.Q(ended_at__isnull=True, user__isnull=True),
                name="uniq_running_timer_null_user_wo",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(ended_at__isnull=True)
                    | models.Q(ended_at__gte=models.F("started_at"))
                ),
                name="timelog_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["work_order", "ended_at"]),
        ]

    def __str__(self):
        return f"{self.work_order_id} — {self.started_at:%d/%m %H:%M}"

    @property
    def is_running(self) -> bool:
        return self.ended_at is None

    @property
    def live_duration_seconds(self) -> int:
        """Duração efetiva: se rodando, agora - início; senão o valor gravado."""
        if self.is_running and self.started_at:
            from django.utils import timezone
            return max(0, int((timezone.now() - self.started_at).total_seconds()))
        return self.duration_seconds

    @property
    def duration_hours(self) -> Decimal:
        return (Decimal(self.live_duration_seconds) / Decimal(3600)).quantize(
            Decimal("0.01")
        )

    @property
    def billable_value(self) -> Decimal:
        if not self.is_billable or not self.rate_applied:
            return Decimal("0.00")
        return (self.duration_hours * self.rate_applied).quantize(Decimal("0.01"))

    def recompute_duration(self):
        if self.ended_at and self.started_at:
            self.duration_seconds = max(
                0, int((self.ended_at - self.started_at).total_seconds())
            )


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

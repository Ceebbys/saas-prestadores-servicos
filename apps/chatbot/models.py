import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TenantOwnedModel, TimestampedModel


class ChatbotFlow(TenantOwnedModel):
    """Fluxo de chatbot configurável (no-code)."""

    class Channel(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        WEBCHAT = "webchat", "WebChat"
        TELEGRAM = "telegram", "Telegram"

    class TriggerType(models.TextChoices):
        FIRST_MESSAGE = "first_message", "Primeira mensagem do cliente"
        KEYWORD = "keyword", "Palavra-chave"
        INACTIVITY = "inactivity", "Inatividade"
        MANUAL = "manual", "Manual / API"

    name = models.CharField("Nome", max_length=100)
    description = models.TextField("Descrição", blank=True)
    is_active = models.BooleanField("Ativo", default=False)
    webhook_token = models.UUIDField(
        "Token do Webhook",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    channel = models.CharField(
        "Canal",
        max_length=20,
        choices=Channel.choices,
        default=Channel.WHATSAPP,
    )
    welcome_message = models.TextField(
        "Mensagem",
        default="Olá! Seja bem-vindo(a). Vou ajudá-lo(a) com algumas perguntas rápidas.",
        help_text="Texto enviado ao iniciar o fluxo (antes do primeiro passo).",
    )
    fallback_message = models.TextField(
        "Mensagem de fallback",
        default="Desculpe, não entendi. Pode repetir?",
    )

    # --- Encerramento ---
    send_completion_message = models.BooleanField(
        "Enviar mensagem ao concluir",
        default=False,
        help_text=(
            "Se ativo, envia a mensagem abaixo quando o cliente termina o fluxo. "
            "Se desativo, o fluxo encerra silenciosamente."
        ),
    )
    completion_message = models.TextField(
        "Mensagem ao concluir",
        blank=True,
        default=(
            "✅ Prontinho! Suas informações foram registradas. "
            "Um de nossos especialistas vai te chamar em breve."
        ),
        help_text="Texto enviado ao final do fluxo (somente se 'Enviar mensagem ao concluir' estiver ativo).",
    )

    # --- Disparo / gatilhos ---
    trigger_type = models.CharField(
        "Tipo de gatilho",
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.FIRST_MESSAGE,
    )
    trigger_keywords = models.CharField(
        "Palavras-chave",
        max_length=500,
        blank=True,
        help_text="Separadas por vírgula. Aplica-se quando 'Tipo de gatilho' = palavra-chave.",
    )
    inactivity_minutes = models.PositiveIntegerField(
        "Inatividade (minutos)",
        null=True,
        blank=True,
        help_text="Disparar após X minutos sem resposta do cliente.",
    )
    priority = models.PositiveIntegerField(
        "Prioridade",
        default=100,
        help_text="Menor valor = maior prioridade. Empate vai por mais recente.",
    )
    cooldown_minutes = models.PositiveIntegerField(
        "Cooldown (minutos)",
        default=60,
        help_text="Tempo mínimo entre dois disparos do mesmo fluxo para a mesma sessão.",
    )
    exclusive = models.BooleanField(
        "Exclusivo",
        default=True,
        help_text="Quando ativo, bloqueia outros fluxos enquanto este estiver em andamento.",
    )

    # RV06 — Builder visual (React Flow). Quando True, executor lê graph_json
    # da versão publicada (motor v2). Setado automaticamente no primeiro
    # publish bem-sucedido da FlowVersion.
    use_visual_builder = models.BooleanField(
        "Construtor visual",
        default=False,
        help_text=(
            "Quando ativo, o fluxo é gerenciado pelo construtor visual e o "
            "executor lê graph_json da versão publicada."
        ),
    )
    current_published_version = models.ForeignKey(
        "ChatbotFlowVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Versão publicada atual",
        help_text="Atalho para o executor (evita lookup por status a cada turno).",
    )

    class Meta:
        verbose_name = "Fluxo de Chatbot"
        verbose_name_plural = "Fluxos de Chatbot"
        ordering = ["priority", "name"]

    def __str__(self):
        return self.name

    @property
    def keyword_list(self) -> list[str]:
        return [
            kw.strip().lower()
            for kw in (self.trigger_keywords or "").split(",")
            if kw.strip()
        ]

    def steps_tree(self):
        """Retorna passos achatados em ordem visual (preorder DFS).

        Cada item: dict com `step` e `nivel` para a UI indentar a árvore.
        Ordem: codigo_hierarquico ASC, com fallback em `subordem` e `order`.
        """
        from collections import defaultdict

        children_map = defaultdict(list)
        roots = []
        for step in self.steps.all():
            if step.parent_id is None:
                roots.append(step)
            else:
                children_map[step.parent_id].append(step)

        # Ordenar irmãos por subordem -> order -> pk.
        sort_key = lambda s: (s.subordem or 0, s.order or 0, s.pk)
        roots.sort(key=sort_key)
        for siblings in children_map.values():
            siblings.sort(key=sort_key)

        flat = []

        def visit(step):
            flat.append({"step": step, "nivel": step.nivel or 0})
            for child in children_map.get(step.pk, []):
                visit(child)

        for root in roots:
            visit(root)
        return flat


class ChatbotStep(TimestampedModel):
    """Passo/pergunta de um fluxo de chatbot."""

    class StepType(models.TextChoices):
        TEXT = "text", "Texto livre"
        CHOICE = "choice", "Escolha"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        NAME = "name", "Nome"
        COMPANY = "company", "Empresa"
        DOCUMENT = "document", "CPF/CNPJ"

    class LeadFieldMapping(models.TextChoices):
        NAME = "name", "Nome"
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Telefone"
        COMPANY = "company", "Empresa"
        DOCUMENT = "cpf_cnpj", "CPF/CNPJ"
        NOTES = "notes", "Observações"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="Fluxo",
    )
    order = models.PositiveIntegerField("Ordem", default=0)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="Etapa pai",
        help_text="Define o agrupamento hierárquico para visualização (1, 1.1, 1.2…).",
    )
    subordem = models.PositiveIntegerField(
        "Subordem",
        default=0,
        help_text="Posição dentro do agrupamento do pai (0, 1, 2…).",
    )
    codigo_hierarquico = models.CharField(
        "Código hierárquico",
        max_length=64,
        blank=True,
        db_index=True,
        editable=False,
        help_text="Calculado automaticamente (ex.: '1.2.3').",
    )
    nivel = models.PositiveSmallIntegerField(
        "Nível",
        default=0,
        editable=False,
        help_text="Profundidade na árvore (raiz = 0).",
    )
    question_text = models.TextField("Pergunta")
    step_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=StepType.choices,
        default=StepType.TEXT,
    )
    lead_field_mapping = models.CharField(
        "Campo do Lead",
        max_length=50,
        blank=True,
        choices=LeadFieldMapping.choices,
        help_text="Campo do lead que receberá a resposta.",
    )
    is_required = models.BooleanField("Obrigatório", default=True)
    is_final = models.BooleanField(
        "Encerrar conversa neste passo",
        default=False,
        help_text=(
            "Marque quando esta etapa representar o fim oficial do atendimento "
            "automático. Ações automáticas configuradas para o passo ainda "
            "rodam, mas nenhum próximo passo é disparado."
        ),
    )

    # --- Preparação para fluxo visual (RV05 FASE 3C) ---
    # Não há UI ainda — apenas backend pronto para futura biblioteca de
    # drag-and-drop (React Flow / Drawflow). Não muda o motor atual de
    # navegação (next_step + codigo_hierarquico).
    class NodeType(models.TextChoices):
        MESSAGE = "message", "Mensagem"
        QUESTION = "question", "Pergunta"
        CONDITION = "condition", "Condição"
        ACTION = "action", "Ação automática"

    node_type = models.CharField(
        "Tipo de nó (visual)",
        max_length=20,
        choices=NodeType.choices,
        default=NodeType.MESSAGE,
        help_text="Categoria visual do nó para futura UI de fluxo. Sem efeito no motor atual.",
    )
    position_x = models.FloatField("Posição X (visual)", default=0.0)
    position_y = models.FloatField("Posição Y (visual)", default=0.0)
    visual_config = models.JSONField(
        "Configuração visual",
        default=dict,
        blank=True,
        help_text="Cor, ícone, etc. — usado por futuro builder visual.",
    )

    class Meta:
        verbose_name = "Passo do Chatbot"
        verbose_name_plural = "Passos do Chatbot"
        ordering = ["codigo_hierarquico", "order"]
        indexes = [
            models.Index(fields=["flow", "parent"]),
            models.Index(fields=["flow", "codigo_hierarquico"]),
        ]

    def __str__(self):
        prefix = self.codigo_hierarquico or str(self.order)
        return f"Passo {prefix}: {self.question_text[:50]}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "Um passo não pode ser pai de si mesmo."})

        # Detecta ciclo: parent não pode estar na subárvore do step atual.
        if self.parent_id and self.pk:
            ancestor = self.parent
            visited = set()
            while ancestor is not None:
                if ancestor.pk == self.pk:
                    raise ValidationError(
                        {"parent": "Ciclo detectado: o pai escolhido descende deste passo."}
                    )
                if ancestor.pk in visited:
                    break
                visited.add(ancestor.pk)
                ancestor = ancestor.parent

        # Pai precisa ser do mesmo fluxo (defesa multiempresa).
        if self.parent_id and self.flow_id and self.parent.flow_id != self.flow_id:
            raise ValidationError({"parent": "O pai precisa pertencer ao mesmo fluxo."})

    def _compute_hierarchy(self):
        """Calcula codigo_hierarquico e nivel walking até a raiz."""
        if self.parent_id is None:
            # Raízes: subordem entre os irmãos no mesmo fluxo sem pai.
            self.nivel = 0
            self.codigo_hierarquico = str(self.subordem + 1) if self.subordem is not None else "1"
            return
        parent = self.parent
        if not parent:
            self.nivel = 0
            self.codigo_hierarquico = str((self.subordem or 0) + 1)
            return
        parent_code = parent.codigo_hierarquico or str((parent.subordem or 0) + 1)
        self.nivel = parent.nivel + 1
        self.codigo_hierarquico = f"{parent_code}.{(self.subordem or 0) + 1}"

    def save(self, *args, **kwargs):
        self._compute_hierarchy()
        super().save(*args, **kwargs)
        # Reescreve descendentes para refletir mudança de pai/subordem.
        for child in self.children.all():
            child.save()


class ChatbotChoice(TimestampedModel):
    """Opção de resposta para um passo do tipo 'choice'."""

    step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.CASCADE,
        related_name="choices",
        verbose_name="Passo",
    )
    text = models.CharField("Texto da opção", max_length=200)
    order = models.PositiveIntegerField("Ordem", default=0)
    next_step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_choices",
        verbose_name="Próximo passo",
        help_text="Se vazio, avança para o próximo passo na ordem.",
    )
    servico = models.ForeignKey(
        "operations.ServiceType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chatbot_choices",
        verbose_name="Serviço associado",
        help_text=(
            "Quando o cliente escolhe esta opção, o serviço é salvo na sessão "
            "e usado em automações futuras (lead, proposta)."
        ),
    )

    class Meta:
        verbose_name = "Opção do Chatbot"
        verbose_name_plural = "Opções do Chatbot"
        ordering = ["order"]

    def __str__(self):
        return self.text


class ChatbotAction(TimestampedModel):
    """Ação executada pelo chatbot em determinado gatilho.

    Dois modos de associação (RV05 FASE 3B):
    1. **Por etapa** (`step != None`, `trigger=ON_STEP`): roda ao executar
       o passo específico. Múltiplas ações por passo, ordenáveis.
    2. **Por fluxo** (`step == None`, `trigger=ON_COMPLETE/TIMEOUT/KEYWORD`):
       comportamento legado — roda ao final do fluxo. Mantido por
       compatibilidade retroativa.

    Constraint impede ambiguidade (step=X com ON_COMPLETE não faz sentido).
    """

    class Trigger(models.TextChoices):
        ON_STEP = "on_step", "Ao executar este passo"
        ON_COMPLETE = "on_complete", "Ao completar o fluxo"
        ON_TIMEOUT = "on_timeout", "Timeout"
        ON_KEYWORD = "on_keyword", "Palavra-chave"

    class ActionType(models.TextChoices):
        CREATE_LEAD = "create_lead", "Criar lead"
        UPDATE_PIPELINE = "update_pipeline", "Atualizar pipeline"
        APPLY_TAG = "apply_tag", "Aplicar tag"
        LINK_SERVICO = "link_servico", "Vincular serviço pré-fixado"
        REGISTER_EVENT = "register_event", "Registrar evento"
        SEND_EMAIL = "send_email", "Enviar e-mail"
        SEND_WHATSAPP = "send_whatsapp", "Enviar WhatsApp"
        CREATE_TASK = "create_task", "Criar tarefa"
        # Tipos legados ainda suportados:
        NOTIFY_USER = "notify_user", "Notificar usuário (legado)"
        SEND_MESSAGE = "send_message", "Enviar mensagem (legado)"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name="Fluxo",
    )
    step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="actions",
        verbose_name="Etapa",
        help_text=(
            "Se preenchido, a ação roda DURANTE a execução desta etapa "
            "(use trigger 'Ao executar este passo'). Se vazio, é uma ação "
            "global do fluxo (legado)."
        ),
    )
    trigger = models.CharField(
        "Gatilho",
        max_length=20,
        choices=Trigger.choices,
        default=Trigger.ON_COMPLETE,
    )
    action_type = models.CharField(
        "Tipo de ação",
        max_length=20,
        choices=ActionType.choices,
        default=ActionType.CREATE_LEAD,
    )
    order = models.PositiveIntegerField(
        "Ordem",
        default=0,
        help_text="Ordem de execução dentro do passo (menor primeiro).",
    )
    is_active = models.BooleanField(
        "Ativa",
        default=True,
        help_text="Desative temporariamente sem perder a configuração.",
    )
    config = models.JSONField(
        "Configuração",
        default=dict,
        blank=True,
        help_text=(
            "Parâmetros específicos do tipo (JSON). Ex.: para 'apply_tag', "
            '{"tag": "qualificado"}; para "send_email", {"to": "...", "subject": "..."}.'
        ),
    )

    class Meta:
        verbose_name = "Ação do Chatbot"
        verbose_name_plural = "Ações do Chatbot"
        ordering = ["step_id", "order", "trigger"]
        indexes = [
            models.Index(fields=["flow", "step", "is_active", "order"]),
            models.Index(fields=["flow", "trigger", "is_active"]),
        ]
        constraints = [
            # Mutex: action com step DEVE ter trigger=on_step; sem step DEVE ter
            # trigger no conjunto legado. Impede config ambígua.
            models.CheckConstraint(
                check=(
                    models.Q(step__isnull=False, trigger="on_step")
                    | models.Q(step__isnull=True) & ~models.Q(trigger="on_step")
                ),
                name="chatbot_action_step_trigger_consistency",
            ),
        ]

    def __str__(self):
        scope = f"step #{self.step_id}" if self.step_id else "flow"
        return f"[{scope}] {self.get_trigger_display()} → {self.get_action_type_display()}"


class ChatbotSession(TimestampedModel):
    """Sessão de conversa de um visitante com o chatbot."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        COMPLETED = "completed", "Concluída"
        EXPIRED = "expired", "Expirada"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name="Fluxo",
    )
    session_key = models.UUIDField(
        "Chave da sessão",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    current_step = models.ForeignKey(
        ChatbotStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Passo atual",
        help_text="Apontador legado para ChatbotStep (motor v1).",
    )
    # RV06 — motor v2 (graph_json) usa current_node_id como apontador na sessão.
    current_node_id = models.CharField(
        "Nó atual (graph_json)",
        max_length=64,
        blank=True,
        help_text="ID do nó atual no graph_json publicado (motor v2). Vazio para fluxos legados.",
    )
    lead_data = models.JSONField("Dados coletados", default=dict, blank=True)
    channel = models.CharField("Canal", max_length=20, default="webchat")
    sender_id = models.CharField("ID do remetente", max_length=255, blank=True)
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    lead = models.ForeignKey(
        "crm.Lead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chatbot_sessions",
        verbose_name="Lead criado",
    )

    class Meta:
        verbose_name = "Sessão do Chatbot"
        verbose_name_plural = "Sessões do Chatbot"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["flow", "status"]),
            models.Index(fields=["session_key"]),
        ]

    def __str__(self):
        return f"Session {self.session_key} ({self.status})"


class WhatsAppConfig(TimestampedModel):
    """Configuração de WhatsApp por empresa (OneToOne)."""

    empresa = models.OneToOneField(
        "accounts.Empresa",
        on_delete=models.CASCADE,
        related_name="whatsapp_config",
        verbose_name="Empresa",
    )
    instance_name = models.CharField(
        "Nome da instância",
        max_length=100,
        unique=True,
        help_text="Identificador único desta instância na Evolution API (ex: empresa-a-whatsapp).",
    )
    phone_number = models.CharField("Número conectado", max_length=20, blank=True)
    api_url = models.URLField(
        "URL da Evolution API",
        blank=True,
        help_text="Deixe em branco para usar a URL global configurada no servidor.",
    )
    api_key = models.CharField(
        "API Key",
        max_length=200,
        blank=True,
        help_text="Deixe em branco para usar a chave global configurada no servidor.",
    )
    instance_token = models.CharField(
        "Token da Instância",
        max_length=200,
        blank=True,
        help_text="Gerado automaticamente pela Evolution API ao criar a instância.",
    )
    is_connected = models.BooleanField("Conectado", default=False)
    connected_at = models.DateTimeField("Conectado em", null=True, blank=True)

    class Meta:
        verbose_name = "Configuracao WhatsApp"
        verbose_name_plural = "Configuracoes WhatsApp"

    def __str__(self):
        return f"{self.empresa.name} — {self.instance_name}"

    @property
    def effective_api_url(self):
        return self.api_url or getattr(settings, "EVOLUTION_API_URL", "")

    @property
    def effective_api_key(self):
        """Chave para operações administrativas (criar instâncias, listar, etc.)."""
        return self.api_key or getattr(settings, "EVOLUTION_API_KEY", "")

    @property
    def effective_instance_key(self):
        """Chave para operações desta instância (enviar, QR code, status, etc.).

        Prioridade: token gerado pela Evolution → api_key override → chave global.
        O instance_token é a chave mais específica e segura para operações por instância.
        """
        return self.instance_token or self.api_key or getattr(settings, "EVOLUTION_API_KEY", "")


class ChatbotFlowDispatch(TenantOwnedModel):
    """Log auditável de quando/por que cada fluxo foi disparado ou bloqueado."""

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="dispatches",
        verbose_name="Fluxo",
    )
    sender_id = models.CharField("Sender ID", max_length=255)
    triggered_at = models.DateTimeField("Disparado em", auto_now_add=True)
    reason = models.CharField(
        "Motivo",
        max_length=200,
        help_text="Ex.: 'first_message', 'inactivity 180min', 'blocked_by:flow_X'.",
    )
    blocked = models.BooleanField("Bloqueado", default=False)
    metadata = models.JSONField("Metadados", default=dict, blank=True)

    class Meta:
        verbose_name = "Disparo de Fluxo"
        verbose_name_plural = "Disparos de Fluxo"
        ordering = ["-triggered_at"]
        indexes = [
            models.Index(fields=["empresa", "flow", "-triggered_at"]),
            models.Index(fields=["sender_id", "-triggered_at"]),
        ]

    def __str__(self):
        prefix = "BLOCKED" if self.blocked else "DISPATCHED"
        return f"{prefix} {self.flow.name} → {self.sender_id} ({self.reason})"


# ---------------------------------------------------------------------------
# RV06 — Builder visual (React Flow island)
# ---------------------------------------------------------------------------


class ChatbotFlowVersion(TimestampedModel):
    """Versão de um fluxo de chatbot — rascunho/publicada/arquivada.

    Cada `ChatbotFlow` pode ter no máximo 1 DRAFT e 1 PUBLISHED ativos.
    Versões anteriores publicadas viram ARCHIVED ao publicar uma nova.

    O motor v2 (`apps.chatbot.builder.services.flow_executor`) interpreta
    `graph_json` da versão PUBLISHED apontada por `flow.current_published_version`.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        PUBLISHED = "published", "Publicada"
        ARCHIVED = "archived", "Arquivada"

    flow = models.ForeignKey(
        ChatbotFlow,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="Fluxo",
    )
    numero = models.PositiveIntegerField(
        "Número da versão",
        help_text="Sequencial por flow. Calculado automaticamente no save().",
    )
    status = models.CharField(
        "Status",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    graph_json = models.JSONField(
        "Grafo (graph_json)",
        default=dict,
        blank=True,
        help_text="Estrutura {nodes, edges, viewport, metadata, schema_version}.",
    )
    schema_version = models.PositiveSmallIntegerField(
        "Versão do schema",
        default=1,
        help_text="Versão do graph_v1 schema; incrementada em breaking changes.",
    )
    validation_errors = models.JSONField(
        "Erros de validação",
        default=list,
        blank=True,
        help_text="Lista de erros do último validate (ou [] se válido).",
    )
    validated_at = models.DateTimeField(
        "Última validação", null=True, blank=True,
    )
    published_at = models.DateTimeField(
        "Publicada em", null=True, blank=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_chatbot_versions",
        verbose_name="Publicada por",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chatbot_versions",
        verbose_name="Criada por",
    )
    notes = models.TextField(
        "Notas de versão",
        blank=True,
        help_text="Release notes opcionais (changelog interno).",
    )

    class Meta:
        verbose_name = "Versão de Fluxo"
        verbose_name_plural = "Versões de Fluxo"
        ordering = ["flow", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["flow", "numero"],
                name="chatbot_flowversion_unique_numero",
            ),
            models.UniqueConstraint(
                fields=["flow"],
                condition=models.Q(status="draft"),
                name="chatbot_flowversion_one_draft_per_flow",
            ),
            models.UniqueConstraint(
                fields=["flow"],
                condition=models.Q(status="published"),
                name="chatbot_flowversion_one_published_per_flow",
            ),
        ]
        indexes = [
            models.Index(fields=["flow", "status"]),
        ]

    def __str__(self):
        return f"{self.flow.name} v{self.numero} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.numero:
            # Calcula próximo número sequencial por flow
            last = (
                ChatbotFlowVersion.objects
                .filter(flow=self.flow)
                .order_by("-numero")
                .first()
            )
            self.numero = (last.numero + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def is_publishable(self) -> bool:
        """True se o último validate foi bem-sucedido (sem erros)."""
        return self.validated_at is not None and not self.validation_errors


class ChatbotMessage(TimestampedModel):
    """Mensagens trocadas durante uma sessão de chatbot.

    Persistência relacional para auditoria, replay e BI futuro.
    Decisão RV06: tabela própria (não JSONField) para queries estruturadas.
    """

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Recebida (usuário → bot)"
        OUTBOUND = "outbound", "Enviada (bot → usuário)"
        SYSTEM = "system", "Sistema"

    session = models.ForeignKey(
        ChatbotSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Sessão",
    )
    direction = models.CharField(
        "Direção",
        max_length=10,
        choices=Direction.choices,
    )
    content = models.TextField("Conteúdo")
    payload = models.JSONField(
        "Payload extra",
        default=dict,
        blank=True,
        help_text="Botões, anexos, raw provider data, metadados.",
    )
    node_id = models.CharField(
        "ID do nó",
        max_length=64,
        blank=True,
        help_text="ID do nó no graph_json OU 'step_<pk>' para fluxos legados.",
    )

    class Meta:
        verbose_name = "Mensagem do Chatbot"
        verbose_name_plural = "Mensagens do Chatbot"
        ordering = ["session", "created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["direction", "created_at"]),
        ]

    def __str__(self):
        return f"{self.direction} @ {self.session_id}: {self.content[:50]}"


class ChatbotExecutionLog(TimestampedModel):
    """Log estruturado de execução por sessão/nó.

    Registra entrada/saída de nós, ações executadas, falhas de validação,
    chamadas API e erros. Base para dashboards de uso/conversão.
    """

    class Event(models.TextChoices):
        NODE_ENTERED = "node_entered", "Nó iniciado"
        NODE_EXITED = "node_exited", "Nó concluído"
        ACTION_EXECUTED = "action_executed", "Ação executada"
        VALIDATION_FAILED = "validation_failed", "Validação falhou"
        API_CALL = "api_call", "Chamada de API"
        ERROR = "error", "Erro"
        SESSION_STARTED = "session_started", "Sessão iniciada"
        SESSION_COMPLETED = "session_completed", "Sessão concluída"

    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Aviso"
        ERROR = "error", "Erro"

    session = models.ForeignKey(
        ChatbotSession,
        on_delete=models.CASCADE,
        related_name="execution_logs",
        verbose_name="Sessão",
    )
    node_id = models.CharField(
        "ID do nó",
        max_length=64,
        blank=True,
    )
    event = models.CharField(
        "Evento",
        max_length=30,
        choices=Event.choices,
    )
    level = models.CharField(
        "Nível",
        max_length=10,
        choices=Level.choices,
        default=Level.INFO,
    )
    payload = models.JSONField(
        "Payload",
        default=dict,
        blank=True,
    )

    class Meta:
        verbose_name = "Log de Execução"
        verbose_name_plural = "Logs de Execução"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["level", "-created_at"]),
            models.Index(fields=["event", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.level}] {self.event} @ {self.node_id or '?'}"


class ChatbotSecret(TenantOwnedModel):
    """Cofre de segredos (API keys, tokens) usados por nós api_call.

    Preparada em RV06-V1 mas SEM UI de CRUD nem uso ativo no executor —
    o bloco api_call está marcado como "coming_soon" no catálogo. A
    integração efetiva (UI de gerenciamento + lazy decrypt no executor)
    fica para a V2.

    Valor encriptado via `apps.core.encryption.Fernet` (mesma chave usada
    em EmpresaEmailConfig).
    """

    name = models.CharField(
        "Nome (slug)",
        max_length=80,
        help_text="Identificador único dentro da empresa. Ex.: 'crm_api_key'.",
    )
    description = models.TextField("Descrição", blank=True)
    value_encrypted = models.BinaryField(
        "Valor (encriptado)",
        help_text="Conteúdo encriptado via Fernet. Nunca exibir em UI.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chatbot_secrets",
        verbose_name="Criado por",
    )
    last_used_at = models.DateTimeField(
        "Último uso", null=True, blank=True,
    )

    class Meta:
        verbose_name = "Segredo do Chatbot"
        verbose_name_plural = "Segredos do Chatbot"
        ordering = ["empresa", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "name"],
                name="chatbot_secret_unique_name_per_empresa",
            ),
        ]

    def __str__(self):
        return f"{self.empresa}: {self.name}"

"""Endpoints JSON do construtor visual (RV06).

Auth = session + CSRF (mesmo padrão do resto do app). Validação de tenant
acontece em `BuilderAPIView.dispatch`. Rate limit aplicado em save/validate/publish.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator

from apps.chatbot.builder.api.auth import BuilderAPIView
from apps.chatbot.builder.schemas import (
    get_flow_template,
    load_flow_templates,
    load_node_catalog,
)
from apps.chatbot.builder.services.flow_converter import convert_legacy_flow_to_graph
from apps.chatbot.builder.services.flow_validator import validate_graph
from apps.chatbot.models import ChatbotFlow, ChatbotFlowVersion
from apps.core.decorators import rate_limit_per_user

logger = logging.getLogger(__name__)

_RL_CALLS = settings.CHATBOT_BUILDER_RATE_LIMIT_CALLS
_RL_WINDOW = settings.CHATBOT_BUILDER_RATE_LIMIT_WINDOW


_EMPTY_GRAPH = {
    "schema_version": 1,
    "viewport": {"x": 0, "y": 0, "zoom": 1},
    "metadata": {},
    "nodes": [
        {
            "id": "n_start",
            "type": "start",
            "position": {"x": 100, "y": 100},
            "data": {"label": "Início"},
        }
    ],
    "edges": [],
}


def _get_or_create_draft(flow: ChatbotFlow, user) -> ChatbotFlowVersion:
    """Retorna a versão draft do flow. Se não existir, cria vazia."""
    draft = (
        ChatbotFlowVersion.objects.filter(flow=flow, status=ChatbotFlowVersion.Status.DRAFT)
        .order_by("-numero")
        .first()
    )
    if draft is None:
        draft = ChatbotFlowVersion.objects.create(
            flow=flow,
            status=ChatbotFlowVersion.Status.DRAFT,
            graph_json=_EMPTY_GRAPH,
            created_by=user if user and user.is_authenticated else None,
        )
    return draft


# ---------------------------------------------------------------------------
# GET /api/chatbot/flows/<pk>/graph/
# ---------------------------------------------------------------------------


class GraphView(BuilderAPIView):
    """Retorna draft graph (cria se não existir)."""

    def get(self, request: HttpRequest, pk: int):
        draft = _get_or_create_draft(self.flow, request.user)
        return JsonResponse({
            "version_id": draft.id,
            "numero": draft.numero,
            "schema_version": draft.schema_version,
            "graph": draft.graph_json or _EMPTY_GRAPH,
            "validation_errors": draft.validation_errors,
            "last_saved_at": draft.updated_at.isoformat() if draft.updated_at else None,
            "use_visual_builder": self.flow.use_visual_builder,
            "has_published": self.flow.current_published_version_id is not None,
            "published_version_id": self.flow.current_published_version_id,
        })


# ---------------------------------------------------------------------------
# POST /api/chatbot/flows/<pk>/graph/save/
# ---------------------------------------------------------------------------


@method_decorator(
    rate_limit_per_user(max_calls=_RL_CALLS, window=_RL_WINDOW),
    name="dispatch",
)
class GraphSaveView(BuilderAPIView):
    """Salva (autosave) o graph atual no draft."""

    def post(self, request: HttpRequest, pk: int):
        body = self.json_body(request)
        if isinstance(body, JsonResponse):
            return body
        graph = body.get("graph")
        if not isinstance(graph, dict):
            return JsonResponse({"error": "missing_graph"}, status=400)

        # Limites mínimos antes de gravar (não roda validação semântica aqui — só limites)
        if len(graph.get("nodes", [])) > settings.CHATBOT_BUILDER_MAX_NODES:
            return JsonResponse({"error": "too_many_nodes"}, status=422)
        if len(graph.get("edges", [])) > settings.CHATBOT_BUILDER_MAX_EDGES:
            return JsonResponse({"error": "too_many_edges"}, status=422)

        draft = _get_or_create_draft(self.flow, request.user)
        draft.graph_json = graph
        draft.validated_at = None  # invalida último validate ao mudar
        draft.save(update_fields=["graph_json", "validated_at", "updated_at"])
        return JsonResponse({
            "ok": True,
            "saved_at": timezone.now().isoformat(),
            "version_id": draft.id,
        })


# ---------------------------------------------------------------------------
# POST /api/chatbot/flows/<pk>/validate/
# ---------------------------------------------------------------------------


@method_decorator(
    rate_limit_per_user(max_calls=_RL_CALLS, window=_RL_WINDOW),
    name="dispatch",
)
class GraphValidateView(BuilderAPIView):
    """Roda validate_graph no draft. Salva resultado em validation_errors."""

    def post(self, request: HttpRequest, pk: int):
        draft = _get_or_create_draft(self.flow, request.user)
        result = validate_graph(draft.graph_json, flow=self.flow)
        draft.validation_errors = result["errors"]
        draft.validated_at = timezone.now()
        draft.save(update_fields=["validation_errors", "validated_at", "updated_at"])
        return JsonResponse({
            "valid": result["valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
        })


# ---------------------------------------------------------------------------
# POST /api/chatbot/flows/<pk>/publish/
# ---------------------------------------------------------------------------


@method_decorator(
    rate_limit_per_user(max_calls=_RL_CALLS, window=_RL_WINDOW),
    name="dispatch",
)
class GraphPublishView(BuilderAPIView):
    """Publica o draft atual (exige validate=True).

    Cria nova versão PUBLISHED, arquiva a anterior, atualiza
    `flow.current_published_version` e marca `use_visual_builder=True`.
    """

    def post(self, request: HttpRequest, pk: int):
        draft = _get_or_create_draft(self.flow, request.user)
        # Re-valida no momento do publish (defesa)
        result = validate_graph(draft.graph_json, flow=self.flow)
        if not result["valid"]:
            return JsonResponse({
                "error": "invalid_graph",
                "message": "Fluxo tem erros — corrija antes de publicar.",
                "errors": result["errors"],
                "warnings": result["warnings"],
            }, status=422)

        with transaction.atomic():
            # RV06-H — select_for_update no row do flow para serializar publishes
            # concorrentes. Sem isso, dois requests simultâneos podem criar 2
            # versões PUBLISHED e a última a fazer save() vence (orfana a outra).
            flow_locked = ChatbotFlow.objects.select_for_update().get(pk=self.flow.pk)

            # Arquiva published anterior
            ChatbotFlowVersion.objects.filter(
                flow=flow_locked, status=ChatbotFlowVersion.Status.PUBLISHED,
            ).update(status=ChatbotFlowVersion.Status.ARCHIVED)

            # Cria nova versão PUBLISHED (snapshot do graph atual do draft)
            now = timezone.now()
            published = ChatbotFlowVersion.objects.create(
                flow=flow_locked,
                graph_json=draft.graph_json,
                schema_version=draft.schema_version,
                validation_errors=[],
                validated_at=now,
                status=ChatbotFlowVersion.Status.PUBLISHED,
                published_at=now,
                published_by=request.user if request.user.is_authenticated else None,
                created_by=draft.created_by,
            )

            # Atualiza flow (row já está locked, save é seguro)
            flow_locked.current_published_version = published
            flow_locked.use_visual_builder = True
            flow_locked.save(update_fields=["current_published_version", "use_visual_builder", "updated_at"])
            self.flow = flow_locked

        return JsonResponse({
            "published_version_id": published.id,
            "numero": published.numero,
            "published_at": published.published_at.isoformat(),
        })


# ---------------------------------------------------------------------------
# POST /api/chatbot/flows/<pk>/builder/init/
# ---------------------------------------------------------------------------


@method_decorator(
    # Conversão pode ser cara para flows legados grandes — limita 10/min/user
    rate_limit_per_user(max_calls=10, window=60),
    name="dispatch",
)
class BuilderInitView(BuilderAPIView):
    """Inicializa o builder: converte legacy → graph_json se draft não existe."""

    def post(self, request: HttpRequest, pk: int):
        existing = (
            ChatbotFlowVersion.objects.filter(
                flow=self.flow, status=ChatbotFlowVersion.Status.DRAFT,
            )
            .order_by("-numero")
            .first()
        )
        if existing is not None:
            return JsonResponse({
                "version_id": existing.id,
                "created": False,
            })
        # Converte fluxo legado
        graph = convert_legacy_flow_to_graph(self.flow)
        draft = ChatbotFlowVersion.objects.create(
            flow=self.flow,
            status=ChatbotFlowVersion.Status.DRAFT,
            graph_json=graph,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return JsonResponse({
            "version_id": draft.id,
            "created": True,
        })


# ---------------------------------------------------------------------------
# GET /api/chatbot/node-catalog/
# ---------------------------------------------------------------------------


from django.contrib.auth.decorators import login_required


@method_decorator(
    rate_limit_per_user(max_calls=120, window=60),
    name="dispatch",
)
class SimulatorStartView(BuilderAPIView):
    """V2B — Inicia simulação usando o DRAFT graph (não a versão publicada)."""

    def post(self, request: HttpRequest, pk: int):
        from apps.chatbot.builder.services.simulator import start_simulation

        draft = _get_or_create_draft(self.flow, request.user)
        result = start_simulation(self.flow, draft.graph_json or _EMPTY_GRAPH)
        return JsonResponse(result)


@method_decorator(
    rate_limit_per_user(max_calls=120, window=60),
    name="dispatch",
)
class SimulatorStepView(BuilderAPIView):
    """V2B — Processa um turno da simulação (stateless: state vai/volta no body)."""

    def post(self, request: HttpRequest, pk: int):
        from apps.chatbot.builder.services.simulator import process_simulation

        body = self.json_body(request)
        if isinstance(body, JsonResponse):
            return body
        state = body.get("state") or {}
        user_response = body.get("response") or ""

        draft = _get_or_create_draft(self.flow, request.user)
        result = process_simulation(draft.graph_json or _EMPTY_GRAPH, state, user_response)
        return JsonResponse(result)


@login_required
@rate_limit_per_user(max_calls=120, window=60)
def flow_templates_view(request: HttpRequest):
    """V2C — Lista templates pré-prontos de fluxo."""
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    return JsonResponse(load_flow_templates())


@method_decorator(
    rate_limit_per_user(max_calls=10, window=60),
    name="dispatch",
)
class ApplyTemplateView(BuilderAPIView):
    """V2C — Aplica um template ao draft do flow (substitui graph atual).

    POST body: {"template_id": "captacao_basica"}
    """

    def post(self, request: HttpRequest, pk: int):
        body = self.json_body(request)
        if isinstance(body, JsonResponse):
            return body
        template_id = (body.get("template_id") or "").strip()
        if not template_id:
            return JsonResponse({"error": "missing_template_id"}, status=400)

        template = get_flow_template(template_id)
        if template is None:
            return JsonResponse({"error": "template_not_found"}, status=404)

        # Backup do graph anterior em ChatbotFlowVersion ARCHIVED antes de
        # sobrescrever (usuário pode "desfazer" via histórico de versões).
        draft = _get_or_create_draft(self.flow, request.user)
        previous_graph = draft.graph_json or {}
        previous_has_content = bool(
            previous_graph.get("nodes")
            and len(previous_graph.get("nodes", [])) > 1
        )
        if previous_has_content:
            ChatbotFlowVersion.objects.create(
                flow=self.flow,
                status=ChatbotFlowVersion.Status.ARCHIVED,
                graph_json=previous_graph,
                schema_version=draft.schema_version,
                notes=f"Backup automático antes de aplicar template '{template['name']}'.",
                created_by=request.user if request.user.is_authenticated else None,
            )

        # Aplica template ao draft
        draft.graph_json = template["graph"]
        draft.validated_at = None
        draft.validation_errors = []
        draft.save(update_fields=["graph_json", "validated_at", "validation_errors", "updated_at"])
        return JsonResponse({
            "ok": True,
            "version_id": draft.id,
            "template_name": template["name"],
            "backup_created": previous_has_content,
        })


@login_required
@rate_limit_per_user(max_calls=120, window=60)  # GET pequeno, 120/min é generoso
def node_catalog_view(request: HttpRequest):
    """Retorna o catálogo de tipos de bloco (público para users logados).

    Não precisa de tenant — catálogo é global. Aceita GET.
    """
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    return JsonResponse(load_node_catalog())


# ---------------------------------------------------------------------------
# GET /api/chatbot/options/<key>/ — dropdown options para PropertiesPanel
# ---------------------------------------------------------------------------


@login_required
@rate_limit_per_user(max_calls=120, window=60)
def chatbot_options_view(request: HttpRequest, key: str):
    """RV06 — Carrega options para selects dinâmicos do builder.

    Usado por `data_fields_per_action_type` em node_catalog para popular
    dropdowns de serviços, pipeline stages, proposal templates, etc.

    Returns: {"options": [{"value": "1", "label": "Topografia"}, ...]}
    """
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)

    empresa = getattr(request, "empresa", None)
    if empresa is None:
        return JsonResponse({"error": "no_active_empresa"}, status=403)

    loader = _OPTIONS_LOADERS.get(key)
    if loader is None:
        return JsonResponse(
            {"error": "unknown_options_key", "key": key,
             "available_keys": list(_OPTIONS_LOADERS.keys())},
            status=404,
        )
    try:
        options = loader(empresa)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro carregando options key=%s empresa=%s", key, empresa.pk)
        return JsonResponse({"error": "load_failed", "detail": str(exc)[:200]}, status=500)
    return JsonResponse({"options": options, "key": key})


def _opts_services(empresa) -> list[dict]:
    from apps.operations.models import ServiceType
    qs = ServiceType.objects.filter(empresa=empresa, is_active=True).order_by("name")
    return [
        {
            "value": str(s.pk),
            "label": s.name,
            "extra": {
                "price": str(s.default_price),
                "prazo_dias": s.default_prazo_dias,
                "category": s.category,
            },
        }
        for s in qs
    ]


def _opts_pipeline_stages(empresa) -> list[dict]:
    from apps.crm.models import PipelineStage
    qs = (
        PipelineStage.objects
        .filter(pipeline__empresa=empresa)
        .select_related("pipeline")
        .order_by("pipeline__name", "order")
    )
    return [
        {"value": str(s.pk), "label": f"{s.pipeline.name} — {s.name}"}
        for s in qs
    ]


def _opts_proposal_templates(empresa) -> list[dict]:
    from apps.proposals.models import ProposalTemplate
    qs = ProposalTemplate.objects.filter(empresa=empresa).order_by("name")
    return [{"value": str(t.pk), "label": t.name} for t in qs]


def _opts_contract_templates(empresa) -> list[dict]:
    from apps.contracts.models import ContractTemplate
    qs = ContractTemplate.objects.filter(empresa=empresa).order_by("name")
    return [{"value": str(t.pk), "label": t.name} for t in qs]


def _opts_tags(empresa) -> list[dict]:
    """Tags já usadas no tenant (autocompletar). Sem dedupe via DISTINCT por simplicidade."""
    from apps.crm.models import LeadTag
    qs = (
        LeadTag.objects.filter(empresa=empresa)
        .values_list("name", flat=True)
        .distinct()
        .order_by("name")
    )
    return [{"value": name, "label": name} for name in qs[:100]]


_OPTIONS_LOADERS = {
    "services": _opts_services,
    "pipeline_stages": _opts_pipeline_stages,
    "proposal_templates": _opts_proposal_templates,
    "contract_templates": _opts_contract_templates,
    "tags": _opts_tags,
}

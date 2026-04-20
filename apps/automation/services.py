"""Serviços de orquestração do pipeline automatizado.

Cada função conecta um passo do fluxo ponta a ponta:
    Chatbot → Lead → Proposta → Contrato → OS → Financeiro

Regras:
- @transaction.atomic para consistência
- Idempotência: verificação antes de criar duplicatas
- Rastreabilidade: cada operação cria um AutomationLog
- Multiempresa: empresa é argumento obrigatório
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .models import AutomationLog


# ---------------------------------------------------------------------------
# Helper: log de automação
# ---------------------------------------------------------------------------

def _log(
    empresa,
    action,
    entity_type,
    entity_id,
    source_entity_type="",
    source_entity_id=None,
    metadata=None,
    status=AutomationLog.Status.SUCCESS,
    error_message="",
):
    return AutomationLog.objects.create(
        empresa=empresa,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        status=status,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        metadata=metadata or {},
        error_message=error_message,
    )


# ---------------------------------------------------------------------------
# 1. Chatbot → Lead
# ---------------------------------------------------------------------------

CHANNEL_SOURCE_MAP = {
    "whatsapp": "whatsapp",
    "webchat": "site",
    "telegram": "outro",
}


@transaction.atomic
def create_lead_from_chatbot(empresa, flow, session_data):
    """Cria um Lead a partir dos dados coletados pelo chatbot.

    Args:
        empresa: Instância de Empresa (tenant)
        flow: Instância de ChatbotFlow (pode ser None para demo)
        session_data: dict com keys: name, email, phone, company, notes, session_id

    Returns:
        Lead criado ou existente (idempotente via external_ref)
    """
    from apps.crm.models import Lead

    session_id = session_data.get("session_id", "")
    if not session_id:
        session_id = f"chatbot:{flow.pk if flow else 0}:{uuid4().hex[:8]}"

    # Idempotência: se já existe lead com este external_ref, retorna
    existing = Lead.objects.filter(
        empresa=empresa, external_ref=session_id,
    ).first()
    if existing:
        return existing

    channel = flow.channel if flow else "whatsapp"
    source = CHANNEL_SOURCE_MAP.get(channel, "outro")

    lead = Lead.objects.create(
        empresa=empresa,
        name=session_data.get("name", "Lead do Chatbot"),
        email=session_data.get("email", ""),
        phone=session_data.get("phone", ""),
        company=session_data.get("company", ""),
        source=source,
        external_ref=session_id,
        notes=session_data.get("notes", ""),
    )

    _log(
        empresa=empresa,
        action=AutomationLog.Action.CHATBOT_TO_LEAD,
        entity_type=AutomationLog.EntityType.LEAD,
        entity_id=lead.pk,
        source_entity_type="chatbot_flow",
        source_entity_id=flow.pk if flow else None,
        metadata={"channel": channel, "session_id": session_id},
    )

    return lead


# ---------------------------------------------------------------------------
# 2. Lead → Proposta
# ---------------------------------------------------------------------------

@transaction.atomic
def create_proposal_from_lead(empresa, lead, template=None, items_data=None):
    """Gera uma Proposta rascunho a partir de um Lead.

    Args:
        empresa: Instância de Empresa
        lead: Instância de Lead
        template: ProposalTemplate (opcional, usa default se None)
        items_data: list[dict] com description, quantity, unit, unit_price (opcional)

    Returns:
        Proposal criada ou existente
    """
    from apps.proposals.models import Proposal, ProposalItem, ProposalTemplate

    # Idempotência: se já existe proposta draft vinculada a este lead via automação
    existing_log = AutomationLog.objects.filter(
        empresa=empresa,
        action=AutomationLog.Action.LEAD_TO_PROPOSAL,
        source_entity_type="lead",
        source_entity_id=lead.pk,
        status=AutomationLog.Status.SUCCESS,
    ).first()
    if existing_log:
        existing = Proposal.objects.filter(pk=existing_log.entity_id).first()
        if existing:
            return existing

    # Resolver template
    if not template:
        template = ProposalTemplate.objects.filter(
            empresa=empresa, is_default=True,
        ).first()

    proposal = Proposal(
        empresa=empresa,
        lead=lead,
        title=f"Proposta para {lead.name}",
        status=Proposal.Status.DRAFT,
        valid_until=timezone.now().date() + timedelta(days=30),
    )

    if template:
        proposal.template = template
        proposal.introduction = template.introduction
        proposal.terms = template.terms
        proposal.payment_method = template.default_payment_method
        proposal.is_installment = template.default_is_installment
        proposal.installment_count = template.default_installment_count

    proposal.save()  # save() auto-generates number

    # Criar itens
    if items_data:
        for i, item in enumerate(items_data):
            ProposalItem.objects.create(
                proposal=proposal,
                description=item.get("description", "Serviço"),
                details=item.get("details", ""),
                quantity=Decimal(str(item.get("quantity", 1))),
                unit=item.get("unit", "un"),
                unit_price=Decimal(str(item.get("unit_price", 0))),
                order=i,
            )
    elif template and template.default_items.exists():
        for i, tpl_item in enumerate(template.default_items.all()):
            ProposalItem.objects.create(
                proposal=proposal,
                description=tpl_item.description,
                details=tpl_item.details,
                quantity=tpl_item.quantity,
                unit=tpl_item.unit,
                unit_price=tpl_item.unit_price,
                order=i,
            )
    else:
        ProposalItem.objects.create(
            proposal=proposal,
            description="Serviço conforme solicitação",
            quantity=Decimal("1.00"),
            unit="un",
            unit_price=Decimal("1500.00"),
            order=0,
        )

    proposal.recalculate_totals()

    _log(
        empresa=empresa,
        action=AutomationLog.Action.LEAD_TO_PROPOSAL,
        entity_type=AutomationLog.EntityType.PROPOSAL,
        entity_id=proposal.pk,
        source_entity_type="lead",
        source_entity_id=lead.pk,
        metadata={"proposal_number": proposal.number, "total": str(proposal.total)},
    )

    return proposal


# ---------------------------------------------------------------------------
# 3. Proposta → Contrato
# ---------------------------------------------------------------------------

@transaction.atomic
def create_contract_from_proposal(empresa, proposal, template=None):
    """Gera um Contrato rascunho a partir de uma Proposta aceita.

    Args:
        empresa: Instância de Empresa
        proposal: Instância de Proposal (idealmente status=accepted)
        template: ContractTemplate (opcional, usa default se None)

    Returns:
        Contract criado ou existente
    """
    from apps.contracts.models import Contract, ContractTemplate

    # Idempotência
    existing = Contract.objects.filter(proposal=proposal).first()
    if existing:
        return existing

    if not template:
        template = ContractTemplate.objects.filter(
            empresa=empresa, is_default=True,
        ).first()

    # Montar conteúdo
    if template and template.content:
        content = template.content
        content = content.replace("{cliente}", proposal.lead.name)
        content = content.replace("{valor}", f"R$ {proposal.total:,.2f}")
        content = content.replace("{proposta}", proposal.number)
    else:
        content = (
            f"Contrato de prestação de serviços firmado com "
            f"{proposal.lead.name}, conforme proposta {proposal.number}, "
            f"no valor total de R$ {proposal.total:,.2f}."
        )

    contract = Contract.objects.create(
        empresa=empresa,
        proposal=proposal,
        lead=proposal.lead,
        title=f"Contrato - {proposal.title}",
        content=content,
        value=proposal.total,
        status=Contract.Status.DRAFT,
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=365),
    )

    _log(
        empresa=empresa,
        action=AutomationLog.Action.PROPOSAL_TO_CONTRACT,
        entity_type=AutomationLog.EntityType.CONTRACT,
        entity_id=contract.pk,
        source_entity_type="proposal",
        source_entity_id=proposal.pk,
        metadata={"contract_number": contract.number, "value": str(contract.value)},
    )

    return contract


# ---------------------------------------------------------------------------
# 4. Contrato → Ordem de Serviço
# ---------------------------------------------------------------------------

@transaction.atomic
def create_work_order_from_contract(empresa, contract, service_type=None):
    """Gera uma Ordem de Serviço a partir de um Contrato assinado.

    Args:
        empresa: Instância de Empresa
        contract: Instância de Contract (idealmente status=signed)
        service_type: ServiceType (opcional, usa primeiro ativo se None)

    Returns:
        WorkOrder criada ou existente
    """
    from apps.operations.models import ServiceType, WorkOrder

    # Idempotência
    existing = WorkOrder.objects.filter(contract=contract).first()
    if existing:
        return existing

    if not service_type:
        service_type = ServiceType.objects.filter(
            empresa=empresa, is_active=True,
        ).first()

    work_order = WorkOrder.objects.create(
        empresa=empresa,
        contract=contract,
        proposal=contract.proposal,
        lead=contract.lead,
        title=f"OS - {contract.title}",
        service_type=service_type,
        status=WorkOrder.Status.PENDING,
        priority=WorkOrder.Priority.MEDIUM,
        description=(
            f"Ordem de serviço gerada automaticamente a partir do "
            f"contrato {contract.number}."
        ),
        scheduled_date=timezone.now().date() + timedelta(days=7),
    )

    _log(
        empresa=empresa,
        action=AutomationLog.Action.CONTRACT_TO_WORK_ORDER,
        entity_type=AutomationLog.EntityType.WORK_ORDER,
        entity_id=work_order.pk,
        source_entity_type="contract",
        source_entity_id=contract.pk,
        metadata={"work_order_number": work_order.number},
    )

    return work_order


# ---------------------------------------------------------------------------
# 5. OS → Financeiro (Cobrança)
# ---------------------------------------------------------------------------

@transaction.atomic
def create_billing_from_work_order(empresa, work_order):
    """Gera lançamentos financeiros a partir de uma OS concluída.

    Reutiliza generate_entries_from_proposal() quando possível.

    Args:
        empresa: Instância de Empresa
        work_order: Instância de WorkOrder (idealmente status=completed)

    Returns:
        list[FinancialEntry]
    """
    from apps.finance.models import FinancialEntry
    from apps.finance.services import generate_entries_from_proposal

    # Idempotência
    existing = list(
        FinancialEntry.objects.filter(
            related_work_order=work_order, auto_generated=True,
        )
    )
    if existing:
        return existing

    entries = []

    # Se há proposta com total > 0, reusar gerador de parcelas
    if work_order.proposal and work_order.proposal.total > 0:
        entries = generate_entries_from_proposal(work_order.proposal)
        # Vincular entries à OS e contrato
        for entry in entries:
            update_fields = []
            if not entry.related_work_order:
                entry.related_work_order = work_order
                update_fields.append("related_work_order")
            if not entry.related_contract and work_order.contract:
                entry.related_contract = work_order.contract
                update_fields.append("related_contract")
            if update_fields:
                update_fields.append("updated_at")
                entry.save(update_fields=update_fields)
    else:
        # Fallback: criar entry único com valor do contrato
        value = (
            work_order.contract.value
            if work_order.contract
            else Decimal("0.00")
        )
        if value > 0:
            entry = FinancialEntry.objects.create(
                empresa=empresa,
                type=FinancialEntry.Type.INCOME,
                description=f"{work_order.number} - Serviço concluído",
                amount=value,
                date=timezone.now().date(),
                status=FinancialEntry.Status.PENDING,
                related_work_order=work_order,
                related_contract=work_order.contract,
                related_proposal=work_order.proposal,
                auto_generated=True,
                notes=(
                    f"Gerado automaticamente a partir da OS "
                    f"{work_order.number}."
                ),
            )
            entries = [entry]

    for entry in entries:
        _log(
            empresa=empresa,
            action=AutomationLog.Action.WORK_ORDER_TO_BILLING,
            entity_type=AutomationLog.EntityType.FINANCIAL_ENTRY,
            entity_id=entry.pk,
            source_entity_type="work_order",
            source_entity_id=work_order.pk,
            metadata={
                "amount": str(entry.amount),
                "work_order_number": work_order.number,
            },
        )

    return entries


# ---------------------------------------------------------------------------
# 6. Pipeline Completo (Demo / Simulação)
# ---------------------------------------------------------------------------

@transaction.atomic
def run_full_pipeline(empresa, flow=None, session_data=None):
    """Executa o pipeline completo para demonstração.

    Cria todas as entidades em sequência, simulando transições de status
    entre os passos (proposta aceita, contrato assinado, OS concluída).

    Args:
        empresa: Instância de Empresa
        flow: ChatbotFlow (opcional, busca primeiro ativo se None)
        session_data: dict com dados do lead (opcional, usa mock se None)

    Returns:
        dict com todas as entidades criadas e logs
    """
    from apps.chatbot.models import ChatbotFlow

    # Resolver flow
    if not flow:
        flow = ChatbotFlow.objects.filter(
            empresa=empresa, is_active=True,
        ).first()

    # Mock session data se não fornecido
    if not session_data:
        session_data = {
            "session_id": f"demo-{uuid4().hex[:8]}",
            "name": "Cliente Demonstração",
            "email": "demo@exemplo.com",
            "phone": "(11) 99999-0000",
            "company": "Empresa Demo",
            "notes": "Lead gerado via simulação de automação",
        }

    result = {"errors": []}

    try:
        # 1. Chatbot → Lead
        lead = create_lead_from_chatbot(empresa, flow, session_data)
        result["lead"] = lead

        # 2. Lead → Proposta
        proposal = create_proposal_from_lead(empresa, lead)
        result["proposal"] = proposal

        # Transição: aceitar proposta
        proposal.status = "accepted"
        proposal.accepted_at = timezone.now()
        proposal.save(update_fields=["status", "accepted_at", "updated_at"])

        # 3. Proposta → Contrato
        contract = create_contract_from_proposal(empresa, proposal)
        result["contract"] = contract

        # Transição: assinar contrato
        contract.status = "signed"
        contract.signed_at = timezone.now()
        contract.save(update_fields=["status", "signed_at", "updated_at"])

        # 4. Contrato → OS
        work_order = create_work_order_from_contract(empresa, contract)
        result["work_order"] = work_order

        # Transição: concluir OS
        work_order.status = "completed"
        work_order.completed_at = timezone.now()
        work_order.save(update_fields=["status", "completed_at", "updated_at"])

        # 5. OS → Financeiro
        entries = create_billing_from_work_order(empresa, work_order)
        result["entries"] = entries

        # Log do pipeline completo
        _log(
            empresa=empresa,
            action=AutomationLog.Action.FULL_PIPELINE,
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=lead.pk,
            metadata={
                "lead_id": lead.pk,
                "proposal_id": proposal.pk,
                "contract_id": contract.pk,
                "work_order_id": work_order.pk,
                "entries_count": len(entries),
                "total": str(proposal.total),
            },
        )

    except Exception as e:
        result["errors"].append(str(e))
        _log(
            empresa=empresa,
            action=AutomationLog.Action.FULL_PIPELINE,
            entity_type=AutomationLog.EntityType.LEAD,
            entity_id=0,
            status=AutomationLog.Status.ERROR,
            error_message=str(e),
        )
        raise

    return result

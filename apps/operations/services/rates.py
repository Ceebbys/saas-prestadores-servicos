"""RV07 (3.1) — Resolução de tarifa horária para apontamentos de horas.

Precedência (do mais específico para o mais geral):
    1. USER     — valor hora do responsável (HourRate scope=user)
    2. JOB_ROLE — valor hora da função do colaborador (Membership.job_role)
    3. TEAM     — valor hora padrão da empresa (HourRate scope=team)
    4. None     — nenhuma tarifa configurada (faturável = 0, sem erro)
"""

from __future__ import annotations

from decimal import Decimal


def resolve_hour_rate(empresa, user) -> tuple[Decimal | None, str]:
    """Retorna ``(valor_hora, origem)`` para o ``user`` na ``empresa``.

    ``origem`` ∈ {"responsavel", "funcao", "equipe", ""}.
    """
    from apps.accounts.models import Membership

    from ..models import HourRate

    if user is not None:
        user_rate = HourRate.objects.filter(
            empresa=empresa, scope=HourRate.Scope.USER, user=user, is_active=True,
        ).first()
        if user_rate:
            return user_rate.hourly_value, "responsavel"

        membership = (
            Membership.objects.filter(empresa=empresa, user=user, is_active=True)
            .select_related("job_role")
            .first()
        )
        if membership and membership.job_role_id:
            role_rate = HourRate.objects.filter(
                empresa=empresa, scope=HourRate.Scope.JOB_ROLE,
                job_role_id=membership.job_role_id, is_active=True,
            ).first()
            if role_rate:
                return role_rate.hourly_value, "funcao"

    team_rate = HourRate.objects.filter(
        empresa=empresa, scope=HourRate.Scope.TEAM, is_active=True,
    ).first()
    if team_rate:
        return team_rate.hourly_value, "equipe"

    return None, ""


def backfill_null_rates(empresa, work_order=None) -> set[int]:
    """RV08 (7.1) — Aplica a tarifa horária a apontamentos que ficaram SEM valor.

    Bug reportado: o valor-hora é "fixado" (snapshot) no apontamento no momento
    do start/stop/lançamento. Quem registrou horas ANTES de configurar o
    valor-hora ficou com ``rate_applied=NULL`` e, mesmo depois de configurar, a
    OS seguia dizendo "valor-hora não configurado" e o faturável/custo dava 0.

    Esta função preenche ``rate_applied``/``rate_source`` desses apontamentos
    resolvendo a tarifa atual. É **idempotente**: só toca logs com
    ``rate_applied IS NULL`` e só persiste quando há tarifa resolvível —
    portanto NÃO re-precifica históricos já fixados (preserva o snapshot).

    Retorna o conjunto de IDs de OS que tiveram apontamentos atualizados.
    """
    from ..models import WorkOrderTimeLog

    qs = WorkOrderTimeLog.objects.filter(
        work_order__empresa=empresa, rate_applied__isnull=True,
    ).select_related("user")
    if work_order is not None:
        qs = qs.filter(work_order=work_order)

    affected: set[int] = set()
    for log in qs:
        rate, source = resolve_hour_rate(empresa, log.user)
        if rate is not None:
            log.rate_applied = rate
            log.rate_source = source
            log.save(update_fields=["rate_applied", "rate_source", "updated_at"])
            affected.add(log.work_order_id)
    return affected

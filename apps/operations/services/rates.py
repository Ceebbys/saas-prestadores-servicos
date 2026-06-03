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

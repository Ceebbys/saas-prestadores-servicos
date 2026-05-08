"""Recalcula codigo_hierarquico e nivel para todos os ChatbotStep.

Útil em duas situações:
1. Após a migração 0008 que adicionou parent/subordem/codigo_hierarquico
   (campos vazios para flows pré-existentes).
2. Quando o usuário reorganiza a árvore manualmente no banco e quer
   regenerar a denormalização.

Estratégia: para cada flow, percorre todos os passos em ordem (raízes
primeiro, depois filhos) e chama save() — que dispara _compute_hierarchy
e propaga para descendentes.

Uso:
    python manage.py rebuild_chatbot_hierarchy [--flow-id N]
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.chatbot.models import ChatbotFlow, ChatbotStep


class Command(BaseCommand):
    help = "Recalcula codigo_hierarquico e nivel para todos os passos de chatbot."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flow-id",
            type=int,
            default=None,
            help="Limita o rebuild a um único fluxo (caso contrário processa todos).",
        )

    def handle(self, *args, **opts):
        flow_qs = ChatbotFlow.objects.all()
        flow_id = opts.get("flow_id")
        if flow_id:
            flow_qs = flow_qs.filter(pk=flow_id)

        total_flows = 0
        total_steps = 0
        for flow in flow_qs.iterator():
            total_flows += 1
            with transaction.atomic():
                steps = list(flow.steps.all())
                # Index por pk para acesso O(1) durante a recursão
                children_map = defaultdict(list)
                roots = []
                for s in steps:
                    if s.parent_id is None:
                        roots.append(s)
                    else:
                        children_map[s.parent_id].append(s)

                # Para flows antigos onde subordem == 0 em todas as raízes,
                # atribui subordem sequencial baseada em `order` para gerar
                # códigos 1, 2, 3 distintos. Não toca onde subordem já foi
                # configurada manualmente (subordem != 0 em pelo menos um).
                if all((r.subordem or 0) == 0 for r in roots) and len(roots) > 1:
                    roots.sort(key=lambda r: (r.order or 0, r.pk))
                    for idx, r in enumerate(roots):
                        r.subordem = idx
                        r.save(update_fields=["subordem"])

                # Recursão: save() já recomputa códigos e propaga para filhos.
                def visit(step, depth=0):
                    nonlocal total_steps
                    step.save()
                    total_steps += 1
                    for child in children_map.get(step.pk, []):
                        visit(child, depth + 1)

                # Visita só raízes; save() em raiz dispara save em filhos.
                for r in roots:
                    visit(r)

            self.stdout.write(
                f"  Flow #{flow.pk} ({flow.name}): {len(steps)} passo(s) processado(s)."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Concluído. {total_flows} fluxo(s), {total_steps} passo(s) atualizados."
            )
        )

"""
Management command para criar fluxos de chatbot WhatsApp completos.

Cria 6 fluxos profissionais por empresa cobrindo todo o ciclo de servico:
1. Atendimento Inicial Completo (12 passos, com ramificacao) - ATIVO
2. Qualificacao e Orcamento (8 passos, linear)
3. Agendamento de Visita Tecnica (7 passos, linear)
4. Acompanhamento de Servico (5 passos, linear)
5. Pesquisa de Satisfacao Completa (6 passos, linear)
6. Captacao de Leads por Campanha (5 passos, linear)

Usage:
    python manage.py create_whatsapp_flows --all
    python manage.py create_whatsapp_flows --empresa=empresa-a
    python manage.py create_whatsapp_flows --all --force
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Empresa
from apps.chatbot.models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep


# ---------------------------------------------------------------------------
# Opcoes de servico por segmento
# ---------------------------------------------------------------------------

SERVICE_CHOICES = {
    "topografia": [
        "Levantamento Planialtimetrico",
        "Georreferenciamento",
        "Demarcacao e Locacao",
        "Regularizacao Fundiaria",
    ],
    "arquitetura": [
        "Projeto Residencial",
        "Projeto Comercial",
        "Reforma e Retrofit",
        "Laudo Tecnico",
    ],
    "engenharia": [
        "Projeto Estrutural",
        "Laudo Tecnico",
        "Fiscalizacao de Obra",
        "Consultoria em Engenharia",
    ],
    "manutencao": [
        "Manutencao Preventiva",
        "Reparo Emergencial",
        "Instalacao",
        "Contrato Mensal",
    ],
    "consultoria": [
        "Consultoria Estrategica",
        "Auditoria",
        "Treinamento In-Company",
        "Assessoria Continua",
    ],
    "informatica": [
        "Desenvolvimento de Software",
        "Infraestrutura/Redes",
        "Suporte Tecnico",
        "Ciberseguranca",
    ],
    "saude": [
        "Consulta Especializada",
        "Exame Diagnostico",
        "Saude Ocupacional",
        "Assessoria em Saude",
    ],
    "juridico": [
        "Consultoria Juridica",
        "Elaboracao de Contrato",
        "Contencioso/Processos",
        "Compliance/Regularizacao",
    ],
}

DEFAULT_CHOICES = [
    "Orcamento Personalizado",
    "Consultoria",
    "Suporte",
    "Outro",
]

URGENCY_CHOICES = [
    "Urgente (ate 3 dias)",
    "Normal (ate 15 dias)",
    "Sem pressa",
]

BUDGET_CHOICES = [
    "Ate R$1.000",
    "R$1.000 a R$5.000",
    "R$5.000 a R$20.000",
    "Acima de R$20.000",
    "Preciso de orientacao",
]

CONTACT_TIME_CHOICES = [
    "Manha (8h-12h)",
    "Tarde (12h-18h)",
    "Noite (18h-21h)",
    "Qualquer horario",
]

VISIT_PERIOD_CHOICES = [
    "Manha",
    "Tarde",
    "Qualquer periodo",
]

FLOW_NAMES = [
    "Atendimento Inicial Completo",
    "Qualificacao e Orcamento",
    "Agendamento de Visita Tecnica",
    "Acompanhamento de Servico",
    "Pesquisa de Satisfacao Completa",
    "Captacao de Leads por Campanha",
]

# Fluxos antigos para limpar com --force
LEGACY_FLOW_NAMES = [
    "Atendimento Completo WhatsApp",
    "Qualificacao Rapida",
    "Pesquisa de Satisfacao",
]


def _add_choices(step, texts, next_steps=None):
    """Helper: cria ChatbotChoice objects para um step."""
    for i, text in enumerate(texts):
        ns = next_steps.get(text) if next_steps else None
        ChatbotChoice.objects.create(step=step, text=text, order=i, next_step=ns)


def _add_action(flow):
    """Helper: adiciona acao on_complete -> create_lead."""
    ChatbotAction.objects.create(
        flow=flow,
        trigger="on_complete",
        action_type="create_lead",
        config={},
    )


class Command(BaseCommand):
    help = "Cria fluxos de chatbot WhatsApp detalhados com exemplos de conversa"

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa", type=str, default="",
            help="Slug da empresa (ex: empresa-a)",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="Criar para todas as empresas",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Deletar fluxos existentes com mesmos nomes antes de recriar",
        )

    def handle(self, *args, **options):
        if options["all"]:
            empresas = Empresa.objects.all()
        elif options["empresa"]:
            empresas = Empresa.objects.filter(slug=options["empresa"])
            if not empresas.exists():
                self.stderr.write(self.style.ERROR(
                    f"Empresa com slug '{options['empresa']}' nao encontrada."
                ))
                return
        else:
            self.stderr.write(self.style.ERROR("Use --all ou --empresa=<slug>"))
            return

        total = 0
        for empresa in empresas:
            count = self._create_flows_for_empresa(empresa, force=options["force"])
            total += count

        self.stdout.write(self.style.SUCCESS(
            f"\n{total} fluxo(s) criado(s) para {empresas.count()} empresa(s)."
        ))

    @transaction.atomic
    def _create_flows_for_empresa(self, empresa, force=False):
        segment = empresa.segment or ""
        choices = SERVICE_CHOICES.get(segment, DEFAULT_CHOICES)

        self.stdout.write(f"\n--- {empresa.name} (segmento: {segment or 'padrao'}) ---")

        if force:
            deleted, _ = ChatbotFlow.objects.filter(
                empresa=empresa, name__in=FLOW_NAMES + LEGACY_FLOW_NAMES,
            ).delete()
            if deleted:
                self.stdout.write(f"  Removidos {deleted} objeto(s) existentes")

        count = 0
        creators = [
            (FLOW_NAMES[0], self._create_flow_1_atendimento_inicial),
            (FLOW_NAMES[1], self._create_flow_2_qualificacao_orcamento),
            (FLOW_NAMES[2], self._create_flow_3_agendamento_visita),
            (FLOW_NAMES[3], self._create_flow_4_acompanhamento),
            (FLOW_NAMES[4], self._create_flow_5_pesquisa_satisfacao),
            (FLOW_NAMES[5], self._create_flow_6_captacao_campanha),
        ]

        for name, creator in creators:
            if not ChatbotFlow.objects.filter(empresa=empresa, name=name).exists():
                creator(empresa, choices)
                count += 1

        return count

    # ===================================================================
    # Flow 1: Atendimento Inicial Completo (12 steps, branching)
    # ===================================================================

    def _create_flow_1_atendimento_inicial(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[0],
            description=(
                "Fluxo principal com triagem inteligente: orcamento (caminho completo "
                "com nome, email, telefone, empresa, servico, urgencia, orcamento) ou "
                "informacoes/suporte/reclamacao (caminho rapido)."
            ),
            is_active=True,
            channel="whatsapp",
            welcome_message=(
                "Ola! Bem-vindo(a) ao nosso atendimento.\n"
                "Sou o assistente virtual e vou te ajudar!"
            ),
            fallback_message="Desculpe, nao entendi sua resposta. Poderia tentar novamente?",
        )

        # --- Steps criados em ordem para poder referenciar nos branches ---

        step0 = ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Como posso ajuda-lo(a) hoje?",
            step_type="choice",
            lead_field_mapping="",
        )
        step1 = ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text=(
                "Para preparar seu orcamento, preciso de algumas informacoes.\n\n"
                "Qual e o seu nome completo?"
            ),
            step_type="name", lead_field_mapping="name",
        )
        step2 = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="Qual e o seu melhor e-mail?",
            step_type="email", lead_field_mapping="email",
        )
        step3 = ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="E o seu telefone com DDD? (Ex: 31 99999-0000)",
            step_type="phone", lead_field_mapping="phone",
        )
        step4 = ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Nome da sua empresa? (Se pessoa fisica, digite 'PF')",
            step_type="company", lead_field_mapping="company",
        )
        step5 = ChatbotStep.objects.create(
            flow=flow, order=5,
            question_text="Qual tipo de servico voce precisa?",
            step_type="choice", lead_field_mapping="notes",
        )
        step6 = ChatbotStep.objects.create(
            flow=flow, order=6,
            question_text="Qual a urgencia?",
            step_type="choice", lead_field_mapping="notes",
        )
        step7 = ChatbotStep.objects.create(
            flow=flow, order=7,
            question_text="Qual a faixa de investimento prevista?",
            step_type="choice", lead_field_mapping="notes",
        )
        step8 = ChatbotStep.objects.create(
            flow=flow, order=8,
            question_text="Descreva brevemente o que voce precisa:",
            step_type="text", lead_field_mapping="notes",
        )
        step9 = ChatbotStep.objects.create(
            flow=flow, order=9,
            question_text=(
                "Perfeito! Suas informacoes foram registradas com sucesso.\n"
                "Entraremos em contato em breve. Obrigado!"
            ),
            step_type="text", lead_field_mapping="notes", is_required=False,
        )
        # --- Branch curto: Informacoes/Suporte/Reclamacao ---
        step10 = ChatbotStep.objects.create(
            flow=flow, order=10,
            question_text="Para agilizar, qual e o seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        step11 = ChatbotStep.objects.create(
            flow=flow, order=11,
            question_text="Descreva sua duvida, solicitacao ou feedback:",
            step_type="text", lead_field_mapping="notes",
        )

        # Choices do step 0 (triagem com branch)
        _add_choices(step0, [
            "Solicitar Orcamento",
            "Informacoes sobre Servicos",
            "Suporte / Acompanhar Servico",
            "Reclamacao / Feedback",
        ], next_steps={
            "Solicitar Orcamento": step1,
            "Informacoes sobre Servicos": step10,
            "Suporte / Acompanhar Servico": step10,
            "Reclamacao / Feedback": step10,
        })

        # Choices do step 5 (servicos por segmento)
        _add_choices(step5, service_choices)

        # Choices do step 6 (urgencia)
        _add_choices(step6, URGENCY_CHOICES)

        # Choices do step 7 (orcamento)
        _add_choices(step7, BUDGET_CHOICES)

        _add_action(flow)
        self.stdout.write(self.style.SUCCESS(
            f"  + {flow.name} (12 passos, ativo)"
        ))

    # ===================================================================
    # Flow 2: Qualificacao e Orcamento (8 steps, linear)
    # ===================================================================

    def _create_flow_2_qualificacao_orcamento(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[1],
            description=(
                "Fluxo focado em qualificacao de lead e coleta de dados para "
                "orcamento detalhado. Coleta nome, telefone, empresa, servico, "
                "escopo, urgencia, orcamento e horario de contato."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message="Ola! Vamos preparar seu orcamento.",
            fallback_message="Nao entendi. Pode repetir, por favor?",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Qual o seu nome completo?",
            step_type="name", lead_field_mapping="name",
        )
        ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Qual seu telefone com DDD?",
            step_type="phone", lead_field_mapping="phone",
        )
        ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="Nome da empresa? (PF se pessoa fisica)",
            step_type="company", lead_field_mapping="company",
        )
        s3 = ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Qual tipo de servico voce precisa?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s3, service_choices)

        ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Descreva o escopo do servico com o maximo de detalhes:",
            step_type="text", lead_field_mapping="notes",
        )
        s5 = ChatbotStep.objects.create(
            flow=flow, order=5,
            question_text="Qual a urgencia?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s5, URGENCY_CHOICES)

        s6 = ChatbotStep.objects.create(
            flow=flow, order=6,
            question_text="Qual a faixa de investimento?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s6, BUDGET_CHOICES)

        s7 = ChatbotStep.objects.create(
            flow=flow, order=7,
            question_text="Qual o melhor horario para contato?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s7, CONTACT_TIME_CHOICES)

        _add_action(flow)
        self.stdout.write(f"  + {flow.name} (8 passos, inativo)")

    # ===================================================================
    # Flow 3: Agendamento de Visita Tecnica (7 steps, linear)
    # ===================================================================

    def _create_flow_3_agendamento_visita(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[2],
            description=(
                "Fluxo para agendamento de visita tecnica. Coleta dados de "
                "contato, endereco, tipo de servico, periodo e descricao."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message="Ola! Vamos agendar sua visita tecnica.",
            fallback_message="Nao entendi. Pode repetir, por favor?",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Qual o seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Qual seu telefone com DDD?",
            step_type="phone", lead_field_mapping="phone",
        )
        ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text=(
                "Qual o endereco completo ou ponto de referencia "
                "para a visita?"
            ),
            step_type="text", lead_field_mapping="notes",
        )
        s3 = ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Qual tipo de servico?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s3, service_choices)

        s4 = ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Qual o melhor periodo para a visita?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s4, VISIT_PERIOD_CHOICES)

        ChatbotStep.objects.create(
            flow=flow, order=5,
            question_text="Descreva brevemente o que precisa ser avaliado:",
            step_type="text", lead_field_mapping="notes",
        )
        ChatbotStep.objects.create(
            flow=flow, order=6,
            question_text="Nome da empresa ou condominio? (PF se residencia)",
            step_type="company", lead_field_mapping="company",
        )

        _add_action(flow)
        self.stdout.write(f"  + {flow.name} (7 passos, inativo)")

    # ===================================================================
    # Flow 4: Acompanhamento de Servico (5 steps, linear)
    # ===================================================================

    def _create_flow_4_acompanhamento(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[3],
            description=(
                "Fluxo para clientes que desejam acompanhar o andamento de "
                "um servico em execucao, tirar duvidas ou reportar problemas."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message="Ola! Vamos verificar o andamento do seu servico.",
            fallback_message="Nao entendi. Pode repetir, por favor?",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Qual o seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text=(
                "Informe o numero do contrato ou ordem de servico "
                "(se tiver, caso contrario digite 'nao tenho'):"
            ),
            step_type="text", lead_field_mapping="notes",
        )
        s2 = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="Voce esta satisfeito com o andamento ate o momento?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s2, [
            "Sim, tudo certo",
            "Tenho duvidas",
            "Tenho um problema",
        ])

        ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Descreva sua duvida ou necessidade adicional:",
            step_type="text", lead_field_mapping="notes",
        )
        s4 = ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Como prefere receber o retorno?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s4, ["WhatsApp", "Telefone", "E-mail"])

        _add_action(flow)
        self.stdout.write(f"  + {flow.name} (5 passos, inativo)")

    # ===================================================================
    # Flow 5: Pesquisa de Satisfacao Completa (6 steps, linear)
    # ===================================================================

    def _create_flow_5_pesquisa_satisfacao(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[4],
            description=(
                "Pesquisa de satisfacao pos-servico. Avalia qualidade, "
                "prazo, atendimento e coleta NPS (indicacao)."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message=(
                "Ola! Obrigado por utilizar nossos servicos.\n"
                "Sua opiniao e muito importante para nos!"
            ),
            fallback_message="Por favor, selecione uma das opcoes ou digite sua resposta.",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Gostariamos de saber sua opiniao. Qual seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        s1 = ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Como voce avalia o servico prestado?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s1, ["Excelente", "Bom", "Regular", "Ruim", "Pessimo"])

        s2 = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="O servico foi entregue no prazo?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s2, [
            "Sim, dentro do prazo",
            "Pequeno atraso",
            "Atraso significativo",
        ])

        s3 = ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Como avalia a qualidade do trabalho?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s3, [
            "Superou expectativas",
            "Atendeu expectativas",
            "Abaixo do esperado",
        ])

        s4 = ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Voce indicaria nossos servicos para outras pessoas?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s4, ["Com certeza!", "Provavelmente", "Talvez", "Nao"])

        ChatbotStep.objects.create(
            flow=flow, order=5,
            question_text="Deixe um comentario, sugestao ou critica:",
            step_type="text", lead_field_mapping="notes", is_required=False,
        )

        _add_action(flow)
        self.stdout.write(f"  + {flow.name} (6 passos, inativo)")

    # ===================================================================
    # Flow 6: Captacao de Leads por Campanha (5 steps, linear)
    # ===================================================================

    def _create_flow_6_captacao_campanha(self, empresa, service_choices):
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name=FLOW_NAMES[5],
            description=(
                "Fluxo rapido e direto para captacao de leads via "
                "campanhas de marketing. Coleta o minimo para contato."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message="Ola! Que bom que voce se interessou!",
            fallback_message="Nao entendi. Pode repetir, por favor?",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Qual o seu nome?",
            step_type="name", lead_field_mapping="name",
        )
        ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Qual seu WhatsApp com DDD?",
            step_type="phone", lead_field_mapping="phone",
        )
        s2 = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="O que mais te interessa?",
            step_type="choice", lead_field_mapping="notes",
        )
        _add_choices(s2, service_choices)

        ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Qual seu e-mail? (ou digite 'pular')",
            step_type="email", lead_field_mapping="email", is_required=False,
        )
        ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Alguma observacao para nossa equipe?",
            step_type="text", lead_field_mapping="notes", is_required=False,
        )

        _add_action(flow)
        self.stdout.write(f"  + {flow.name} (5 passos, inativo)")

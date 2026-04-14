"""
Management command para criar fluxos de chatbot WhatsApp detalhados.

Cria 3 fluxos profissionais por empresa:
1. Atendimento Completo (7 passos, com ramificação)
2. Qualificação Rápida (4 passos, linear)
3. Pesquisa de Satisfação (4 passos, linear)

Usage:
    python manage.py create_whatsapp_flows --all
    python manage.py create_whatsapp_flows --empresa=empresa-a
    python manage.py create_whatsapp_flows --all --force
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Empresa
from apps.chatbot.models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep


# Opções de serviço por segmento da empresa
SERVICE_CHOICES = {
    "topografia": [
        "Levantamento Planialtimétrico",
        "Georreferenciamento",
        "Demarcação e Locação",
        "Regularização Fundiária",
    ],
    "arquitetura": [
        "Projeto Residencial",
        "Projeto Comercial",
        "Reforma e Retrofit",
        "Laudo Técnico",
    ],
    "manutencao": [
        "Manutenção Preventiva",
        "Reparo Emergencial",
        "Instalação",
        "Contrato Mensal",
    ],
    "consultoria": [
        "Consultoria Estratégica",
        "Auditoria",
        "Treinamento In-Company",
        "Assessoria Contínua",
    ],
    "informatica": [
        "Desenvolvimento de Software",
        "Infraestrutura/Redes",
        "Suporte Técnico",
        "Cibersegurança",
    ],
}

DEFAULT_CHOICES = [
    "Orçamento Personalizado",
    "Consultoria",
    "Suporte",
    "Outro",
]

FLOW_NAMES = [
    "Atendimento Completo WhatsApp",
    "Qualificação Rápida",
    "Pesquisa de Satisfação",
]


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
                    f"Empresa com slug '{options['empresa']}' não encontrada."
                ))
                return
        else:
            self.stderr.write(self.style.ERROR(
                "Use --all ou --empresa=<slug>"
            ))
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

        self.stdout.write(f"\n--- {empresa.name} (segmento: {segment or 'padrão'}) ---")

        if force:
            deleted, _ = ChatbotFlow.objects.filter(
                empresa=empresa, name__in=FLOW_NAMES,
            ).delete()
            if deleted:
                self.stdout.write(f"  Removidos {deleted} objeto(s) existentes")

        count = 0

        # Flow 1: Atendimento Completo (com ramificação)
        if not ChatbotFlow.objects.filter(empresa=empresa, name=FLOW_NAMES[0]).exists():
            self._create_flow_atendimento_completo(empresa, choices)
            count += 1

        # Flow 2: Qualificação Rápida
        if not ChatbotFlow.objects.filter(empresa=empresa, name=FLOW_NAMES[1]).exists():
            self._create_flow_qualificacao_rapida(empresa, choices[:3])
            count += 1

        # Flow 3: Pesquisa de Satisfação
        if not ChatbotFlow.objects.filter(empresa=empresa, name=FLOW_NAMES[2]).exists():
            self._create_flow_pesquisa_satisfacao(empresa)
            count += 1

        return count

    def _create_flow_atendimento_completo(self, empresa, service_choices):
        """Fluxo completo com 7 passos e ramificação na primeira escolha."""
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name="Atendimento Completo WhatsApp",
            description=(
                "Fluxo principal de atendimento via WhatsApp com captação completa "
                "de dados do lead, escolha de serviço por segmento e ramificação "
                "inteligente para diferentes tipos de atendimento."
            ),
            is_active=True,
            channel="whatsapp",
            welcome_message=(
                "Olá! 👋 Bem-vindo(a) ao nosso atendimento.\n"
                "Sou o assistente virtual e vou te ajudar!"
            ),
            fallback_message="Desculpe, não entendi sua resposta. Poderia tentar novamente?",
        )

        # Step 0: Triagem inicial (choice com ramificação)
        step0 = ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Como posso ajudá-lo(a) hoje?",
            step_type="choice",
            lead_field_mapping="",
            is_required=True,
        )

        # Step 1: Nome (orçamento path)
        step1 = ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text=(
                "Para preparar seu orçamento, preciso de algumas informações.\n\n"
                "Qual é o seu nome completo?"
            ),
            step_type="name",
            lead_field_mapping="name",
            is_required=True,
        )

        # Step 2: Email
        step2 = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="Obrigado! Qual é o seu melhor e-mail para enviarmos o orçamento?",
            step_type="email",
            lead_field_mapping="email",
            is_required=True,
        )

        # Step 3: Telefone
        step3 = ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="E o seu telefone com DDD?\n(Ex: 11 99999-0000)",
            step_type="phone",
            lead_field_mapping="phone",
            is_required=True,
        )

        # Step 4: Tipo de serviço (choice por segmento)
        step4 = ChatbotStep.objects.create(
            flow=flow, order=4,
            question_text="Qual tipo de serviço você precisa?",
            step_type="choice",
            lead_field_mapping="notes",
            is_required=True,
        )

        # Step 5: Empresa
        step5 = ChatbotStep.objects.create(
            flow=flow, order=5,
            question_text=(
                "Qual é o nome da sua empresa?\n"
                "(Se pessoa física, digite 'PF')"
            ),
            step_type="company",
            lead_field_mapping="company",
            is_required=False,
        )

        # Step 6: Descrição livre
        step6 = ChatbotStep.objects.create(
            flow=flow, order=6,
            question_text="Para finalizar, descreva brevemente o que você precisa:",
            step_type="text",
            lead_field_mapping="notes",
            is_required=False,
        )

        # Choices do step 0 (triagem) com ramificação
        # "Solicitar Orçamento" -> step 1 (caminho completo)
        # Outros -> step 5 (caminho rápido: empresa + descrição)
        ChatbotChoice.objects.create(
            step=step0, text="Solicitar Orçamento", order=0,
            next_step=step1,
        )
        ChatbotChoice.objects.create(
            step=step0, text="Acompanhar Serviço", order=1,
            next_step=step5,
        )
        ChatbotChoice.objects.create(
            step=step0, text="Suporte Técnico", order=2,
            next_step=step5,
        )
        ChatbotChoice.objects.create(
            step=step0, text="Falar com Atendente", order=3,
            next_step=step5,
        )

        # Choices do step 4 (serviços por segmento)
        for i, svc in enumerate(service_choices):
            ChatbotChoice.objects.create(step=step4, text=svc, order=i)

        # Action: criar lead ao completar
        ChatbotAction.objects.create(
            flow=flow,
            trigger="on_complete",
            action_type="create_lead",
            config={},
        )

        self.stdout.write(self.style.SUCCESS(
            f"  +{flow.name} (7 passos, ativo)"
        ))

    def _create_flow_qualificacao_rapida(self, empresa, service_choices):
        """Fluxo rápido com 4 passos lineares."""
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name="Qualificação Rápida",
            description=(
                "Fluxo simplificado para qualificação rápida de leads. "
                "Coleta nome, telefone e interesse em apenas 4 passos."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message="Oi! 😊 Vou te atender rapidinho!",
            fallback_message="Não entendi. Pode repetir, por favor?",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Para começar, me diz seu nome?",
            step_type="name",
            lead_field_mapping="name",
            is_required=True,
        )

        ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Qual seu WhatsApp com DDD?",
            step_type="phone",
            lead_field_mapping="phone",
            is_required=True,
        )

        step_svc = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="O que você precisa?",
            step_type="choice",
            lead_field_mapping="notes",
            is_required=True,
        )
        for i, svc in enumerate(service_choices):
            ChatbotChoice.objects.create(step=step_svc, text=svc, order=i)

        ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Alguma informação adicional? (ou digite 'não')",
            step_type="text",
            lead_field_mapping="notes",
            is_required=False,
        )

        ChatbotAction.objects.create(
            flow=flow,
            trigger="on_complete",
            action_type="create_lead",
            config={},
        )

        self.stdout.write(f"  +{flow.name} (4 passos, inativo)")

    def _create_flow_pesquisa_satisfacao(self, empresa):
        """Fluxo de pesquisa de satisfação pós-serviço."""
        flow = ChatbotFlow.objects.create(
            empresa=empresa,
            name="Pesquisa de Satisfação",
            description=(
                "Pesquisa de satisfação enviada após a conclusão do serviço. "
                "Coleta avaliação, indicação e comentários do cliente."
            ),
            is_active=False,
            channel="whatsapp",
            welcome_message=(
                "Olá! Obrigado por utilizar nossos serviços.\n"
                "Sua opinião é muito importante para nós!"
            ),
            fallback_message="Por favor, selecione uma das opções ou digite sua resposta.",
        )

        ChatbotStep.objects.create(
            flow=flow, order=0,
            question_text="Gostaríamos de saber sua opinião.\nQual seu nome?",
            step_type="name",
            lead_field_mapping="name",
            is_required=True,
        )

        step_rating = ChatbotStep.objects.create(
            flow=flow, order=1,
            question_text="Como você avalia nosso atendimento?",
            step_type="choice",
            lead_field_mapping="notes",
            is_required=True,
        )
        for i, text in enumerate(["Excelente", "Bom", "Regular", "Ruim"]):
            ChatbotChoice.objects.create(step=step_rating, text=text, order=i)

        step_nps = ChatbotStep.objects.create(
            flow=flow, order=2,
            question_text="Você indicaria nossos serviços para outras pessoas?",
            step_type="choice",
            lead_field_mapping="notes",
            is_required=True,
        )
        for i, text in enumerate(["Sim, com certeza!", "Talvez", "Não"]):
            ChatbotChoice.objects.create(step=step_nps, text=text, order=i)

        ChatbotStep.objects.create(
            flow=flow, order=3,
            question_text="Deixe um comentário ou sugestão:",
            step_type="text",
            lead_field_mapping="notes",
            is_required=False,
        )

        ChatbotAction.objects.create(
            flow=flow,
            trigger="on_complete",
            action_type="create_lead",
            config={},
        )

        self.stdout.write(f"  +{flow.name} (4 passos, inativo)")

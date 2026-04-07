"""
Management command para popular o banco com dados de demonstração.

Cria 5 empresas demo com usuários, pipelines, leads, propostas,
contratos, ordens de serviço e lançamentos financeiros coerentes.

Uso:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --force
"""

import os
import random
from datetime import time, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# ---------------------------------------------------------------------------
# Nomes brasileiros curados
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Ana", "Carlos", "Maria", "João", "Fernanda", "Pedro", "Juliana",
    "Lucas", "Beatriz", "Rafael", "Camila", "Gustavo", "Larissa",
    "Thiago", "Isabela", "Marcos", "Patrícia", "André", "Vanessa",
    "Roberto", "Cláudia", "Eduardo", "Renata", "Felipe", "Tatiana",
    "Diego", "Adriana", "Leandro", "Sandra", "Henrique", "Daniela",
    "Marcelo", "Priscila", "Alexandre", "Carla", "Rodrigo", "Aline",
    "Bruno", "Simone", "Ricardo", "Cristiane",
]

LAST_NAMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira",
    "Almeida", "Pereira", "Lima", "Carvalho", "Ribeiro", "Gomes",
    "Martins", "Araújo", "Barbosa", "Melo", "Nascimento", "Monteiro",
    "Moreira", "Castro", "Teixeira", "Correia", "Freitas", "Pinto",
    "Nunes", "Vieira", "Cardoso", "Mendes", "Rocha", "Dias",
]

LEAD_SOURCES = ["site", "indicacao", "google", "instagram", "whatsapp", "telefone", "outro"]
LEAD_SOURCE_WEIGHTS = [20, 20, 15, 15, 15, 10, 5]

EMAIL_DOMAINS = ["gmail.com", "outlook.com", "hotmail.com", "yahoo.com.br", "uol.com.br"]

DDD_LIST = ["11", "21", "31", "41", "51", "61", "19", "27", "48", "71"]

LOCATIONS_SP = [
    "Rua Augusta, 1200 - Consolação, São Paulo - SP",
    "Av. Paulista, 1578 - Bela Vista, São Paulo - SP",
    "Rua Oscar Freire, 379 - Jardins, São Paulo - SP",
    "Av. Faria Lima, 2500 - Pinheiros, São Paulo - SP",
    "Rua Haddock Lobo, 595 - Cerqueira César, São Paulo - SP",
]

LOCATIONS_RJ = [
    "Av. Rio Branco, 156 - Centro, Rio de Janeiro - RJ",
    "Rua Visconde de Pirajá, 414 - Ipanema, Rio de Janeiro - RJ",
    "Av. Atlântica, 1702 - Copacabana, Rio de Janeiro - RJ",
]

LOCATIONS_OTHER = [
    "Av. Afonso Pena, 1500 - Centro, Belo Horizonte - MG",
    "Rua XV de Novembro, 300 - Centro, Curitiba - PR",
    "Av. Borges de Medeiros, 800 - Centro, Porto Alegre - RS",
    "SCS Quadra 1, Bloco A - Asa Sul, Brasília - DF",
    "Rua da Aurora, 500 - Boa Vista, Recife - PE",
    "Av. Sete de Setembro, 200 - Centro, Salvador - BA",
    "Rua Felipe Schmidt, 100 - Centro, Florianópolis - SC",
]

ALL_LOCATIONS = LOCATIONS_SP + LOCATIONS_RJ + LOCATIONS_OTHER

# ---------------------------------------------------------------------------
# Definições das 5 empresas demo
# ---------------------------------------------------------------------------
COMPANIES = [
    {
        "name": "GeoPrime Topografia",
        "segment": "topografia",
        "document": "12.345.678/0001-90",
        "email": "contato@geoprime.com.br",
        "phone": "(11) 3456-7890",
        "address": "Rua das Coordenadas, 150 - Pinheiros, São Paulo - SP",
        "volume": "heavy",
        "users": [
            {"role": "owner", "full_name": "Ricardo Mendes", "prefix": "admin"},
            {"role": "manager", "full_name": "Camila Torres", "prefix": "comercial"},
            {"role": "member", "full_name": "Bruno Almeida", "prefix": "tecnico"},
            {"role": "member", "full_name": "Fernanda Costa", "prefix": "financeiro"},
        ],
        "pipeline_stages": [
            ("Primeiro Contato", 0, "#6366F1", False, False),
            ("Levantamento de Campo", 1, "#8B5CF6", False, False),
            ("Processamento", 2, "#F59E0B", False, False),
            ("Entrega Técnica", 3, "#F97316", False, False),
            ("Fechado/Ganho", 4, "#10B981", True, False),
            ("Fechado/Perdido", 5, "#EF4444", False, True),
            ("Pós-Venda", 6, "#06B6D4", False, False),
        ],
        "service_types": [
            ("Levantamento Planialtimétrico", "Levantamento topográfico completo com estação total e GNSS", 24.0),
            ("Georreferenciamento de Imóvel", "Georreferenciamento para registro em cartório conforme INCRA", 16.0),
            ("Locação de Obra", "Demarcação de pontos e eixos para início de construção", 8.0),
            ("Mapeamento Aéreo com Drone", "Aerofotogrametria com drone e geração de ortomosaico", 12.0),
            ("Cadastro de Redes", "Levantamento cadastral de redes de água, esgoto ou elétrica", 16.0),
        ],
        "proposal_items": [
            ("Levantamento planialtimétrico cadastral", "un", 3500, 8000),
            ("Georreferenciamento de imóvel rural", "ha", 150, 350),
            ("Locação de obra", "un", 1200, 3000),
            ("Mapeamento aerofotogramétrico", "km²", 2500, 6000),
            ("Memorial descritivo", "un", 800, 2000),
            ("Planta topográfica", "un", 500, 1500),
            ("Cadastro de rede subterrânea", "km", 1800, 4000),
            ("Nivelamento geométrico", "km", 600, 1500),
        ],
        "client_companies": [
            "Construtora Horizonte", "Imobiliária Central", "Prefeitura de Campinas",
            "Fazenda São Jorge", "Condomínio Villa Verde", "Engenharia Prática Ltda",
            "Loteamento Solar", "Incorporadora Delta", "MRV Regional",
            "Secretaria de Obras Municipal", "Cartório 3º Ofício", "Fazenda Boa Vista",
        ],
        "checklist_templates": [
            ("Levantamento de Campo", [
                "Verificar calibração do equipamento",
                "Conferir carga das baterias",
                "Definir pontos de controle",
                "Coletar dados GNSS",
                "Fotografar marcos e referências",
                "Registrar condições climáticas",
                "Backup dos dados em campo",
            ]),
            ("Entrega de Projeto", [
                "Processar dados brutos",
                "Gerar planta topográfica",
                "Elaborar memorial descritivo",
                "Revisar coordenadas e cotas",
                "Formatar conforme normas ABNT",
                "Enviar para aprovação do cliente",
            ]),
        ],
        "financial_categories_extra": [
            ("Equipamentos", "expense"),
            ("Combustível", "expense"),
            ("Diárias de Campo", "expense"),
            ("Levantamentos", "income"),
            ("Licenças de Software", "expense"),
        ],
    },
    {
        "name": "Studio Alto Arquitetura",
        "segment": "arquitetura",
        "document": "23.456.789/0001-01",
        "email": "contato@studioalto.com.br",
        "phone": "(21) 2345-6789",
        "address": "Rua do Lavradio, 85 - Centro, Rio de Janeiro - RJ",
        "volume": "standard",
        "users": [
            {"role": "owner", "full_name": "Mariana Lopes", "prefix": "admin"},
            {"role": "manager", "full_name": "Gabriel Oliveira", "prefix": "comercial"},
            {"role": "member", "full_name": "Juliana Ferreira", "prefix": "tecnico"},
            {"role": "member", "full_name": "Paulo Ribeiro", "prefix": "financeiro"},
        ],
        "pipeline_stages": [
            ("Contato Inicial", 0, "#6366F1", False, False),
            ("Briefing", 1, "#8B5CF6", False, False),
            ("Estudo Preliminar", 2, "#A855F7", False, False),
            ("Anteprojeto", 3, "#F59E0B", False, False),
            ("Projeto Executivo", 4, "#F97316", False, False),
            ("Fechado/Ganho", 5, "#10B981", True, False),
            ("Fechado/Perdido", 6, "#EF4444", False, True),
            ("Pós-Venda", 7, "#06B6D4", False, False),
        ],
        "service_types": [
            ("Projeto Residencial", "Projeto arquitetônico completo para residências", 120.0),
            ("Projeto Comercial", "Projeto para lojas, escritórios e espaços comerciais", 160.0),
            ("Design de Interiores", "Projeto de interiores com especificação de materiais", 80.0),
            ("Reforma e Retrofit", "Projeto de reforma com adequação estrutural", 60.0),
            ("Regularização de Imóvel", "Projeto para aprovação e regularização em prefeitura", 40.0),
        ],
        "proposal_items": [
            ("Estudo preliminar arquitetônico", "un", 5000, 15000),
            ("Anteprojeto arquitetônico", "m²", 30, 80),
            ("Projeto executivo", "m²", 50, 120),
            ("Acompanhamento de obra", "mês", 3000, 8000),
            ("Projeto de interiores", "m²", 40, 100),
            ("Maquete eletrônica 3D", "un", 2000, 5000),
            ("Projeto de paisagismo", "un", 3000, 8000),
            ("Regularização em prefeitura", "un", 2500, 6000),
        ],
        "client_companies": [
            "Família Andrade", "Restaurante Sabor & Arte", "Clínica Bem Estar",
            "Escritório Advocacia Leal", "Coworking Hub Digital", "Hotel Boutique Carioca",
            "Escola Montessori", "Academia FitPro", "Galeria de Arte Moderna",
        ],
        "checklist_templates": [
            ("Visita ao Terreno", [
                "Fotografar o terreno/imóvel",
                "Medir dimensões principais",
                "Verificar orientação solar",
                "Avaliar topografia e acessos",
                "Consultar vizinhança e gabarito",
            ]),
            ("Entrega de Projeto", [
                "Revisar plantas baixas",
                "Conferir cortes e fachadas",
                "Verificar memorial descritivo",
                "Preparar apresentação para cliente",
                "Gerar arquivo PDF final",
            ]),
        ],
        "financial_categories_extra": [
            ("Renderização 3D", "expense"),
            ("Plotagem", "expense"),
            ("Projetos Arquitetônicos", "income"),
        ],
    },
    {
        "name": "Alfa Assistência Técnica",
        "segment": "manutencao",
        "document": "34.567.890/0001-12",
        "email": "contato@alfaassistencia.com.br",
        "phone": "(31) 3456-7890",
        "address": "Av. do Contorno, 2500 - Funcionários, Belo Horizonte - MG",
        "volume": "standard",
        "users": [
            {"role": "owner", "full_name": "Antônio Vieira", "prefix": "admin"},
            {"role": "manager", "full_name": "Luciana Cardoso", "prefix": "comercial"},
            {"role": "member", "full_name": "Márcio Nunes", "prefix": "tecnico"},
            {"role": "member", "full_name": "Débora Freitas", "prefix": "financeiro"},
        ],
        "pipeline_stages": [
            ("Solicitação", 0, "#6366F1", False, False),
            ("Visita Técnica", 1, "#8B5CF6", False, False),
            ("Orçamento", 2, "#F59E0B", False, False),
            ("Reparo", 3, "#F97316", False, False),
            ("Finalização", 4, "#14B8A6", False, False),
            ("Fechado/Ganho", 5, "#10B981", True, False),
            ("Fechado/Perdido", 6, "#EF4444", False, True),
            ("Pós-Venda", 7, "#06B6D4", False, False),
        ],
        "service_types": [
            ("Manutenção Preventiva", "Inspeção e manutenção preventiva de equipamentos", 4.0),
            ("Manutenção Corretiva", "Reparo de equipamentos com defeito", 6.0),
            ("Instalação de Equipamento", "Instalação e configuração de novos equipamentos", 8.0),
            ("Visita Técnica", "Visita para diagnóstico e orçamento", 2.0),
            ("Troca de Peças", "Substituição de componentes desgastados", 3.0),
        ],
        "proposal_items": [
            ("Visita técnica de diagnóstico", "un", 150, 300),
            ("Manutenção preventiva", "un", 200, 800),
            ("Reparo de equipamento", "un", 300, 1500),
            ("Instalação de peça de reposição", "un", 100, 500),
            ("Calibração de instrumento", "un", 250, 600),
            ("Contrato de manutenção mensal", "mês", 800, 2500),
            ("Laudo técnico", "un", 400, 1000),
        ],
        "client_companies": [
            "Padaria Pão Dourado", "Supermercado Boa Compra", "Laboratório Exame",
            "Frigorífico Boi Gordo", "Hospital Santa Clara", "Condomínio Park Tower",
            "Restaurante Mineiro", "Farmácia Saúde", "Shopping Center Sul",
        ],
        "checklist_templates": [
            ("Visita Técnica", [
                "Identificar modelo e série do equipamento",
                "Testar funcionamento atual",
                "Verificar tensão e corrente",
                "Fotografar componentes",
                "Listar peças necessárias",
                "Informar prazo ao cliente",
            ]),
            ("Finalização do Reparo", [
                "Testar equipamento reparado",
                "Verificar parâmetros de funcionamento",
                "Limpar área de trabalho",
                "Coletar assinatura do cliente",
                "Emitir ordem de serviço finalizada",
            ]),
        ],
        "financial_categories_extra": [
            ("Peças e Componentes", "expense"),
            ("Ferramentas", "expense"),
            ("Manutenções", "income"),
        ],
    },
    {
        "name": "Campo Forte Consultoria",
        "segment": "consultoria",
        "document": "45.678.901/0001-23",
        "email": "contato@campoforte.com.br",
        "phone": "(61) 3456-7890",
        "address": "SCS Quadra 2, Bloco C, Sala 401 - Asa Sul, Brasília - DF",
        "volume": "minimal",
        "users": [
            {"role": "owner", "full_name": "Helena Martins", "prefix": "admin"},
            {"role": "manager", "full_name": "Renato Barbosa", "prefix": "comercial"},
            {"role": "member", "full_name": "Cíntia Araújo", "prefix": "tecnico"},
            {"role": "member", "full_name": "Fábio Teixeira", "prefix": "financeiro"},
        ],
        "pipeline_stages": [
            ("Prospecção", 0, "#6366F1", False, False),
            ("Diagnóstico", 1, "#8B5CF6", False, False),
            ("Proposta", 2, "#F59E0B", False, False),
            ("Plano de Ação", 3, "#F97316", False, False),
            ("Entrega", 4, "#14B8A6", False, False),
            ("Fechado/Ganho", 5, "#10B981", True, False),
            ("Fechado/Perdido", 6, "#EF4444", False, True),
            ("Pós-Venda", 7, "#06B6D4", False, False),
        ],
        "service_types": [
            ("Diagnóstico Organizacional", "Análise completa de processos e gestão", 40.0),
            ("Consultoria Estratégica", "Planejamento estratégico e plano de ação", 80.0),
            ("Treinamento In Company", "Capacitação presencial para equipes", 16.0),
            ("Auditoria de Processos", "Avaliação de conformidade e eficiência", 24.0),
        ],
        "proposal_items": [
            ("Diagnóstico organizacional", "un", 5000, 12000),
            ("Plano de ação estratégico", "un", 8000, 20000),
            ("Consultoria mensal", "mês", 4000, 10000),
            ("Treinamento de equipe", "turma", 3000, 8000),
            ("Relatório de auditoria", "un", 6000, 15000),
        ],
        "client_companies": [
            "Cooperativa AgroBem", "Prefeitura de Uberaba", "ONG Semear",
            "Associação Comercial", "Sindicato Rural", "Escola Técnica Federal",
        ],
        "checklist_templates": [
            ("Diagnóstico Inicial", [
                "Agendar reunião de kick-off",
                "Levantar documentos internos",
                "Entrevistar gestores-chave",
                "Mapear processos atuais",
                "Elaborar relatório de diagnóstico",
            ]),
        ],
        "financial_categories_extra": [
            ("Viagens", "expense"),
            ("Hospedagem", "expense"),
            ("Consultorias", "income"),
        ],
    },
    {
        "name": "Luz & Instalações",
        "segment": "outro",
        "document": "56.789.012/0001-34",
        "email": "contato@luzinstalacoes.com.br",
        "phone": "(41) 3456-7890",
        "address": "Rua Marechal Deodoro, 630 - Centro, Curitiba - PR",
        "volume": "standard",
        "users": [
            {"role": "owner", "full_name": "Sérgio Rocha", "prefix": "admin"},
            {"role": "manager", "full_name": "Viviane Dias", "prefix": "comercial"},
            {"role": "member", "full_name": "Anderson Moreira", "prefix": "tecnico"},
            {"role": "member", "full_name": "Patrícia Gomes", "prefix": "financeiro"},
        ],
        "pipeline_stages": [
            ("Contato", 0, "#6366F1", False, False),
            ("Vistoria", 1, "#8B5CF6", False, False),
            ("Orçamento", 2, "#F59E0B", False, False),
            ("Instalação", 3, "#F97316", False, False),
            ("Testes", 4, "#14B8A6", False, False),
            ("Entrega", 5, "#06B6D4", False, False),
            ("Fechado/Ganho", 6, "#10B981", True, False),
            ("Fechado/Perdido", 7, "#EF4444", False, True),
            ("Pós-Venda", 8, "#06B6D4", False, False),
        ],
        "service_types": [
            ("Instalação Elétrica Residencial", "Instalação completa de rede elétrica residencial", 16.0),
            ("Instalação Elétrica Comercial", "Instalação de rede elétrica comercial e industrial", 40.0),
            ("Quadro de Distribuição", "Montagem e instalação de quadros de distribuição", 8.0),
            ("Instalação de Luminárias", "Instalação de iluminação e automação", 6.0),
            ("Laudo Elétrico NR-10", "Laudo técnico conforme norma NR-10", 12.0),
            ("Manutenção Elétrica", "Manutenção preventiva e corretiva de instalações", 4.0),
        ],
        "proposal_items": [
            ("Vistoria técnica", "un", 200, 500),
            ("Instalação de ponto elétrico", "ponto", 80, 200),
            ("Quadro de distribuição", "un", 800, 2500),
            ("Teste e comissionamento", "un", 500, 1500),
            ("Instalação de luminária LED", "un", 50, 150),
            ("Cabeamento estruturado", "ponto", 120, 300),
            ("Laudo elétrico NR-10", "un", 1500, 4000),
            ("Aterramento", "un", 600, 1800),
        ],
        "client_companies": [
            "Condomínio Residencial Aurora", "Loja Fashion Center", "Padaria Trigo & Mel",
            "Galpão Industrial Metálica", "Clínica Odonto Mais", "Escola Infantil Arco-Íris",
            "Escritório Contábil Balanço", "Restaurante Tempero Bom", "Academia PowerFit",
            "Farmácia Central",
        ],
        "checklist_templates": [
            ("Vistoria Elétrica", [
                "Verificar disjuntores e fusíveis",
                "Medir resistência de aterramento",
                "Testar circuitos com multímetro",
                "Inspecionar fiação e conexões",
                "Verificar quadro de distribuição",
                "Fotografar pontos críticos",
            ]),
            ("Instalação Completa", [
                "Conferir projeto elétrico",
                "Passar eletrodutos e fiação",
                "Instalar quadro de distribuição",
                "Instalar tomadas e interruptores",
                "Instalar luminárias",
                "Testar todos os circuitos",
                "Medir consumo e balanceamento",
                "Emitir certificado de conformidade",
            ]),
        ],
        "financial_categories_extra": [
            ("Material Elétrico", "expense"),
            ("Ferramentas e EPIs", "expense"),
            ("Instalações", "income"),
        ],
    },
]

VOLUME_CONFIG = {
    "heavy":    {"leads": 40, "proposals": 20, "contracts": 15, "work_orders": 25, "entries": 40},
    "standard": {"leads": 28, "proposals": 14, "contracts": 9, "work_orders": 16, "entries": 28},
    "minimal":  {"leads": 15, "proposals": 8, "contracts": 5, "work_orders": 8, "entries": 15},
}


class Command(BaseCommand):
    help = "Popula o banco de dados com dados de demonstração ricos e coerentes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Força execução mesmo com dados demo existentes",
        )

    def handle(self, *args, **options):
        if not self._is_safe_to_run():
            self.stderr.write(self.style.ERROR(
                "Bloqueado: defina DEBUG=True ou DEMO_SEED=true no ambiente."
            ))
            return

        from apps.accounts.models import User

        if User.objects.filter(email__endswith=".demo").exists() and not options["force"]:
            self.stderr.write(self.style.WARNING(
                "Dados demo já existem. Use 'python manage.py reset_demo_data' "
                "ou adicione --force."
            ))
            return

        self.rng = random.Random(42)
        self.today = timezone.now().date()
        self.now = timezone.now()
        self.counters = {}

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== SEED DE DADOS DEMO ===\n"))

        with transaction.atomic():
            for company_def in COMPANIES:
                self._seed_company(company_def)

        self._print_summary()

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _is_safe_to_run(self):
        return (
            getattr(settings, "DEBUG", False)
            or os.environ.get("DEMO_SEED", "").lower() == "true"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _random_date(self, days_back_max=180):
        if days_back_max <= 30:
            days = self.rng.randint(0, days_back_max)
        elif days_back_max <= 90:
            bucket = self.rng.random()
            if bucket < 0.5:
                days = self.rng.randint(0, 30)
            else:
                days = self.rng.randint(31, days_back_max)
        else:
            bucket = self.rng.random()
            if bucket < 0.35:
                days = self.rng.randint(0, 30)
            elif bucket < 0.65:
                days = self.rng.randint(31, 90)
            else:
                days = self.rng.randint(91, days_back_max)
        return self.today - timedelta(days=days)

    def _random_datetime(self, days_back_max=180):
        d = self._random_date(days_back_max)
        hour = self.rng.randint(7, 18)
        minute = self.rng.choice([0, 15, 30, 45])
        return timezone.make_aware(
            timezone.datetime(d.year, d.month, d.day, hour, minute)
        )

    def _random_phone(self):
        ddd = self.rng.choice(DDD_LIST)
        return f"({ddd}) 9{self.rng.randint(1000, 9999)}-{self.rng.randint(1000, 9999)}"

    def _random_email(self, name):
        parts = name.lower().replace("á", "a").replace("é", "e").replace("í", "i")
        parts = parts.replace("ó", "o").replace("ú", "u").replace("ã", "a")
        parts = parts.replace("õ", "o").replace("ç", "c").replace("â", "a")
        parts = parts.replace("ê", "e").replace("ô", "o")
        first = parts.split()[0]
        last = parts.split()[-1] if len(parts.split()) > 1 else ""
        domain = self.rng.choice(EMAIL_DOMAINS)
        return f"{first}.{last}{self.rng.randint(1, 99)}@{domain}"

    def _random_value(self, min_v, max_v):
        return Decimal(str(round(self.rng.uniform(min_v, max_v), 2)))

    def _pick(self, items, weights=None):
        if weights:
            return self.rng.choices(items, weights=weights, k=1)[0]
        return self.rng.choice(items)

    def _backdate(self, model_class, pk, dt):
        if isinstance(dt, timezone.datetime.__class__.__bases__[0]):
            pass
        if not hasattr(dt, "hour"):
            dt = timezone.make_aware(
                timezone.datetime(dt.year, dt.month, dt.day,
                                  self.rng.randint(8, 17), self.rng.choice([0, 15, 30, 45]))
            )
        model_class.objects.filter(pk=pk).update(created_at=dt)

    def _random_name(self):
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def _future_date(self, days_min=5, days_max=60):
        return self.today + timedelta(days=self.rng.randint(days_min, days_max))

    def _past_date(self, days_min=1, days_max=30):
        return self.today - timedelta(days=self.rng.randint(days_min, days_max))

    # ------------------------------------------------------------------
    # Main seeding per company
    # ------------------------------------------------------------------

    def _seed_company(self, cdef):
        name = cdef["name"]
        vol = VOLUME_CONFIG[cdef["volume"]]
        self.stdout.write(f"  Criando {name}...")

        empresa = self._create_empresa(cdef)
        users = self._create_users(empresa, cdef)
        pipeline, stages = self._create_pipeline(empresa, cdef)
        service_types = self._create_service_types(empresa, cdef)
        self._create_proposal_templates(empresa, cdef)
        self._create_contract_templates(empresa, cdef)
        checklist_templates = self._create_checklist_templates(empresa, cdef)
        categories = self._create_categories(empresa, cdef)
        bank_accounts = self._create_bank_accounts(empresa, cdef)
        teams = self._create_teams(empresa, users, cdef)
        self._create_chatbot_flows(empresa, cdef)

        leads = self._create_leads(empresa, users, cdef, vol["leads"])
        opportunities = self._create_opportunities(empresa, leads, pipeline, stages, users)
        proposals = self._create_proposals(empresa, leads, opportunities, cdef, vol["proposals"])
        contracts = self._create_contracts(empresa, leads, proposals, cdef, vol["contracts"])
        work_orders = self._create_work_orders(
            empresa, leads, proposals, contracts, service_types,
            checklist_templates, users, teams, cdef, vol["work_orders"]
        )
        self._create_financial_entries(
            empresa, proposals, contracts, work_orders, categories,
            bank_accounts, cdef, vol["entries"]
        )

        self.counters[name] = vol
        self.stdout.write(self.style.SUCCESS(f"    [OK] {name} concluída"))

    # ------------------------------------------------------------------
    # Phase 1: Foundation
    # ------------------------------------------------------------------

    def _create_empresa(self, cdef):
        from apps.accounts.models import Empresa
        return Empresa.objects.create(
            name=cdef["name"],
            segment=cdef["segment"],
            document=cdef["document"],
            email=cdef["email"],
            phone=cdef["phone"],
            address=cdef["address"],
        )

    def _create_users(self, empresa, cdef):
        from apps.accounts.models import Membership, User

        role_map = {"owner": "owner", "manager": "manager", "member": "member"}
        users = []
        for udef in cdef["users"]:
            email = f"{udef['prefix']}@{empresa.slug}.demo"
            user = User.objects.create_user(
                email=email,
                full_name=udef["full_name"],
                password="Demo123!",
                phone=self._random_phone(),
            )
            user.active_empresa = empresa
            user.save(update_fields=["active_empresa"])
            Membership.objects.create(
                user=user,
                empresa=empresa,
                role=role_map[udef["role"]],
            )
            users.append(user)
        return users

    # ------------------------------------------------------------------
    # Phase 2: Configuration
    # ------------------------------------------------------------------

    def _create_pipeline(self, empresa, cdef):
        from apps.crm.models import Pipeline, PipelineStage

        pipeline = Pipeline.objects.create(
            empresa=empresa,
            name="Pipeline Principal",
            is_default=True,
        )
        stages = []
        for stage_name, order, color, is_won, is_lost in cdef["pipeline_stages"]:
            stage = PipelineStage.objects.create(
                pipeline=pipeline,
                name=stage_name,
                order=order,
                color=color,
                is_won=is_won,
                is_lost=is_lost,
            )
            stages.append(stage)
        return pipeline, stages

    def _create_service_types(self, empresa, cdef):
        from apps.operations.models import ServiceType

        types = []
        for st_name, st_desc, st_hours in cdef["service_types"]:
            st = ServiceType.objects.create(
                empresa=empresa,
                name=st_name,
                description=st_desc,
                estimated_duration_hours=Decimal(str(st_hours)),
            )
            types.append(st)
        return types

    def _create_proposal_templates(self, empresa, cdef):
        from apps.proposals.models import ProposalTemplate, ProposalTemplateItem

        segment = cdef["name"].split()[-1]
        default_tpl = ProposalTemplate.objects.create(
            empresa=empresa,
            name=f"Proposta Padrão - {segment}",
            introduction=(
                f"Prezado(a) cliente,\n\n"
                f"Temos o prazer de apresentar nossa proposta para os serviços "
                f"de {segment.lower()}."
            ),
            terms=(
                "Validade: 30 dias.\n"
                "Pagamento: conforme condições acordadas.\n"
                "Execução: conforme cronograma definido no aceite."
            ),
            default_payment_method="pix",
            default_is_installment=False,
            default_installment_count=None,
            content=(
                f"Os serviços descritos abaixo serão executados conforme "
                f"especificações técnicas e prazos acordados."
            ),
            header_content=f"{cdef['name']} - Proposta Comercial",
            footer_content=(
                f"{cdef['name']}\n"
                f"CNPJ: {cdef['document']}\n"
                f"{cdef['address']}\n"
                f"Tel: {cdef['phone']}"
            ),
            is_default=True,
        )
        # Itens padrão: pega até 3 dos proposal_items do segmento
        for order, (desc, unit, min_p, max_p) in enumerate(cdef["proposal_items"][:3]):
            ProposalTemplateItem.objects.create(
                template=default_tpl,
                description=desc,
                quantity=Decimal("1"),
                unit=unit,
                unit_price=self._random_value(min_p, max_p),
                order=order,
            )

        detailed_tpl = ProposalTemplate.objects.create(
            empresa=empresa,
            name=f"Proposta Detalhada Parcelada - {segment}",
            introduction=(
                f"PROPOSTA TÉCNICA E COMERCIAL\n\n"
                f"Objeto: Prestação de serviços de {segment.lower()} "
                f"conforme escopo detalhado."
            ),
            terms=(
                "1. PRAZO: Conforme cronograma acordado.\n"
                "2. PAGAMENTO: Parcelado em até 3x no cartão ou boleto.\n"
                "3. GARANTIA: 90 dias sobre os serviços executados."
            ),
            default_payment_method="boleto",
            default_is_installment=True,
            default_installment_count=3,
            content=(
                f"1. OBJETO\nPrestação de serviços de {segment.lower()}.\n\n"
                f"2. ESCOPO\nConforme itens listados.\n\n"
                f"3. CONDIÇÕES\nConforme termos."
            ),
            header_content=f"{cdef['name']} - Proposta Técnica",
            footer_content=f"Documento gerado por {cdef['name']}",
            is_default=False,
        )
        for order, (desc, unit, min_p, max_p) in enumerate(cdef["proposal_items"][:2]):
            ProposalTemplateItem.objects.create(
                template=detailed_tpl,
                description=desc,
                quantity=Decimal("1"),
                unit=unit,
                unit_price=self._random_value(min_p, max_p),
                order=order,
            )

    def _create_contract_templates(self, empresa, cdef):
        from apps.contracts.models import ContractTemplate

        segment = cdef["name"].split()[-1]
        ContractTemplate.objects.create(
            empresa=empresa,
            name=f"Contrato Padrão - {segment}",
            content=(
                f"CONTRATO DE PRESTAÇÃO DE SERVIÇOS\n\n"
                f"Pelo presente instrumento particular, as partes abaixo qualificadas:\n\n"
                f"CONTRATADA: {cdef['name']}, inscrita no CNPJ sob nº {cdef['document']}, "
                f"com sede em {cdef['address']}.\n\n"
                f"CONTRATANTE: [Nome do Cliente]\n\n"
                f"Têm entre si justo e contratado o seguinte:\n\n"
                f"CLÁUSULA 1ª - DO OBJETO\n"
                f"A CONTRATADA se obriga a prestar serviços de {segment.lower()} "
                f"conforme escopo definido na proposta anexa.\n\n"
                f"CLÁUSULA 2ª - DO PRAZO\n"
                f"O prazo de execução será conforme cronograma acordado.\n\n"
                f"CLÁUSULA 3ª - DO VALOR\n"
                f"O valor total dos serviços é conforme proposta comercial aceita."
            ),
            is_default=True,
        )

    def _create_checklist_templates(self, empresa, cdef):
        from apps.operations.models import ChecklistItem, ChecklistTemplate

        templates = []
        for tmpl_name, items in cdef["checklist_templates"]:
            tmpl = ChecklistTemplate.objects.create(
                empresa=empresa,
                name=tmpl_name,
            )
            for i, item_desc in enumerate(items):
                ChecklistItem.objects.create(
                    template=tmpl,
                    description=item_desc,
                    order=i,
                )
            templates.append(tmpl)
        return templates

    def _create_categories(self, empresa, cdef):
        from apps.finance.models import FinancialCategory

        default_cats = [
            ("Serviços", "income"), ("Consultoria", "income"),
            ("Produtos", "income"), ("Outros Recebimentos", "income"),
            ("Salários", "expense"), ("Aluguel", "expense"),
            ("Material", "expense"), ("Transporte", "expense"),
            ("Impostos", "expense"), ("Outros Gastos", "expense"),
        ]
        cats = {"income": [], "expense": []}
        for cat_name, cat_type in default_cats + cdef["financial_categories_extra"]:
            cat = FinancialCategory.objects.create(
                empresa=empresa, name=cat_name, type=cat_type,
            )
            cats[cat_type].append(cat)
        return cats

    def _create_bank_accounts(self, empresa, cdef):
        from apps.finance.models import BankAccount

        segment = cdef["name"].split()[-1]
        banks = [
            ("Itaú", "341"), ("Bradesco", "237"), ("Banco do Brasil", "001"),
            ("Santander", "033"), ("Caixa", "104"), ("Nubank", "260"),
            ("Inter", "077"), ("Sicoob", "756"),
        ]
        bank1 = self.rng.choice(banks)
        bank2 = self.rng.choice([b for b in banks if b[0] != bank1[0]])

        pj = BankAccount.objects.create(
            empresa=empresa,
            name=f"Conta PJ {bank1[0]}",
            bank_name=bank1[0],
            bank_code=bank1[1],
            agency=f"{self.rng.randint(1, 9999):04d}",
            account_number=f"{self.rng.randint(10000, 999999):06d}-{self.rng.randint(0,9)}",
            account_type=BankAccount.AccountType.CHECKING,
            person_type=BankAccount.PersonType.PJ,
            holder_name=cdef["name"],
            holder_document=cdef["document"],
            pix_key=cdef["document"].replace(".", "").replace("/", "").replace("-", ""),
            is_default=True,
            is_active=True,
        )

        pf = BankAccount.objects.create(
            empresa=empresa,
            name=f"Conta PF {bank2[0]}",
            bank_name=bank2[0],
            bank_code=bank2[1],
            agency=f"{self.rng.randint(1, 9999):04d}",
            account_number=f"{self.rng.randint(10000, 999999):06d}-{self.rng.randint(0,9)}",
            account_type=BankAccount.AccountType.CHECKING,
            person_type=BankAccount.PersonType.PF,
            holder_name=f"Sócio - {segment}",
            holder_document="",
            pix_key=f"socio@{empresa.slug}.com.br",
            is_default=False,
            is_active=True,
        )
        return [pj, pf]

    def _create_teams(self, empresa, users, cdef):
        from apps.operations.models import Team, TeamMember

        # Teams variam por segmento — realistas para cada tipo de empresa
        TEAM_DEFS = {
            "topografia": [
                ("Equipe de Campo", "Levantamentos e medições em campo", "emerald"),
                ("Equipe de Processamento", "Processamento de dados e entregas técnicas", "indigo"),
            ],
            "arquitetura": [
                ("Equipe de Projetos", "Desenvolvimento de projetos arquitetônicos", "violet"),
                ("Equipe de Obra", "Acompanhamento e execução de obras", "amber"),
            ],
            "manutencao": [
                ("Equipe Técnica A", "Manutenção preventiva e corretiva", "sky"),
                ("Equipe Técnica B", "Instalações e reparos emergenciais", "rose"),
                ("Equipe de Suporte", "Atendimento e diagnóstico remoto", "teal"),
            ],
            "consultoria": [
                ("Equipe de Consultores", "Consultoria técnica especializada", "indigo"),
            ],
            "informatica": [
                ("Equipe de Desenvolvimento", "Desenvolvimento de software e sistemas", "violet"),
                ("Equipe de Infraestrutura", "Servidores, redes e suporte", "slate"),
            ],
        }

        segment = cdef["segment"]
        team_defs = TEAM_DEFS.get(segment, [
            ("Equipe Principal", "Equipe de execução de serviços", "indigo"),
        ])

        # 60% das empresas têm equipes (as que têm mais de 2 usuários)
        if len(users) <= 2:
            return []

        teams = []
        tech_users = [u for u in users if u.email.startswith("tecnico")]
        all_non_owner = [u for u in users if not u.email.startswith("admin")]

        for i, (name, desc, color) in enumerate(team_defs):
            leader = tech_users[i % len(tech_users)] if tech_users else users[0]
            team = Team.objects.create(
                empresa=empresa,
                name=name,
                description=desc,
                leader=leader,
                color=color,
                is_active=True,
            )
            # Add leader as leader role
            TeamMember.objects.create(
                team=team, user=leader, role=TeamMember.Role.LEADER,
            )
            # Add 1-2 additional members
            available = [u for u in all_non_owner if u != leader]
            n_extra = min(self.rng.randint(1, 2), len(available))
            for member_user in self.rng.sample(available, n_extra):
                TeamMember.objects.create(
                    team=team, user=member_user, role=TeamMember.Role.MEMBER,
                )
            teams.append(team)

        return teams

    def _create_chatbot_flows(self, empresa, cdef):
        from apps.chatbot.models import ChatbotAction, ChatbotChoice, ChatbotFlow, ChatbotStep

        segment = cdef["segment"]

        # Nomes de serviço variam por segmento
        SERVICE_CHOICES = {
            "topografia": ["Levantamento topográfico", "Georreferenciamento", "Demarcação de terreno"],
            "arquitetura": ["Projeto arquitetônico", "Reforma residencial", "Laudo técnico"],
            "manutencao": ["Manutenção preventiva", "Reparo emergencial", "Instalação de equipamento"],
            "consultoria": ["Consultoria técnica", "Auditoria", "Treinamento"],
            "informatica": ["Desenvolvimento de sistema", "Suporte técnico", "Infraestrutura de rede"],
        }
        choices = SERVICE_CHOICES.get(segment, ["Solicitar orçamento", "Acompanhar serviço", "Falar com atendente"])

        # --- Flow 1: Captação WhatsApp (ativo) ---
        flow1 = ChatbotFlow.objects.create(
            empresa=empresa,
            name="Captação WhatsApp - Orçamento",
            description="Fluxo principal de captação de leads via WhatsApp com coleta de dados para orçamento.",
            is_active=True,
            channel="whatsapp",
            welcome_message="Olá! 👋 Bem-vindo ao nosso atendimento. Vou te ajudar a solicitar um orçamento de forma rápida.",
            fallback_message="Desculpe, não entendi. Poderia reformular sua resposta?",
        )

        step1 = ChatbotStep.objects.create(
            flow=flow1, order=0, question_text="Para começar, qual é o seu nome completo?",
            step_type="name", lead_field_mapping="name", is_required=True,
        )
        step2 = ChatbotStep.objects.create(
            flow=flow1, order=1, question_text="Ótimo! Qual é o seu e-mail para contato?",
            step_type="email", lead_field_mapping="email", is_required=True,
        )
        step3 = ChatbotStep.objects.create(
            flow=flow1, order=2, question_text="E o seu telefone com DDD?",
            step_type="phone", lead_field_mapping="phone", is_required=True,
        )
        step4 = ChatbotStep.objects.create(
            flow=flow1, order=3, question_text="Qual serviço você tem interesse?",
            step_type="choice", lead_field_mapping="notes", is_required=True,
        )
        for i, choice_text in enumerate(choices):
            ChatbotChoice.objects.create(step=step4, text=choice_text, order=i)

        step5 = ChatbotStep.objects.create(
            flow=flow1, order=4, question_text="Por fim, qual é o nome da sua empresa? (opcional)",
            step_type="company", lead_field_mapping="company", is_required=False,
        )

        ChatbotAction.objects.create(
            flow=flow1, trigger="on_complete", action_type="create_lead", config={},
        )

        # --- Flow 2: Atendimento Rápido (inativo) ---
        flow2 = ChatbotFlow.objects.create(
            empresa=empresa,
            name="Atendimento Rápido",
            description="Fluxo simplificado para triagem rápida de atendimento.",
            is_active=False,
            channel="whatsapp",
            welcome_message="Olá! Selecione uma opção para continuar:",
            fallback_message="Por favor, selecione uma das opções disponíveis.",
        )

        step_a = ChatbotStep.objects.create(
            flow=flow2, order=0, question_text="Como podemos te ajudar?",
            step_type="choice", lead_field_mapping="", is_required=True,
        )
        for i, text in enumerate(["Solicitar orçamento", "Acompanhar serviço", "Falar com atendente"]):
            ChatbotChoice.objects.create(step=step_a, text=text, order=i)

        ChatbotStep.objects.create(
            flow=flow2, order=1, question_text="Qual é o seu nome?",
            step_type="name", lead_field_mapping="name", is_required=True,
        )
        ChatbotStep.objects.create(
            flow=flow2, order=2, question_text="E o seu telefone com DDD?",
            step_type="phone", lead_field_mapping="phone", is_required=True,
        )

        ChatbotAction.objects.create(
            flow=flow2, trigger="on_complete", action_type="create_lead", config={},
        )
        ChatbotAction.objects.create(
            flow=flow2, trigger="on_complete", action_type="notify_user", config={},
        )

    # ------------------------------------------------------------------
    # Phase 3: Transactional data
    # ------------------------------------------------------------------

    def _create_leads(self, empresa, users, cdef, count):
        from apps.crm.models import Lead

        statuses = ["novo", "contatado", "qualificado", "perdido", "convertido"]
        status_weights = [25, 20, 25, 15, 15]
        client_companies = cdef["client_companies"]

        leads_by_status = {"novo": [], "contatado": [], "qualificado": [], "perdido": [], "convertido": []}
        assignable_users = users[:3]  # admin, comercial, tecnico

        for i in range(count):
            name = self._random_name()
            status = self._pick(statuses, status_weights)
            source = self._pick(LEAD_SOURCES, LEAD_SOURCE_WEIGHTS)
            company = self.rng.choice(client_companies) if self.rng.random() > 0.2 else ""
            created_date = self._random_date()

            # Newer leads are more likely to be novo
            if status == "novo":
                created_date = self._random_date(30)
            elif status == "convertido":
                created_date = self._random_date(120)

            lead = Lead.objects.create(
                empresa=empresa,
                name=name,
                email=self._random_email(name),
                phone=self._random_phone(),
                company=company,
                source=source,
                status=status,
                notes=self._lead_notes(status, cdef),
                assigned_to=self.rng.choice(assignable_users) if self.rng.random() > 0.2 else None,
            )
            self._backdate(Lead, lead.pk, created_date)
            leads_by_status[status].append(lead)

        # Guarantee enough qualified leads to fill every pipeline stage
        n_active_stages = len([s for s in cdef["pipeline_stages"] if not s[3] and not s[4]])
        min_qual = max(n_active_stages, 3 if cdef["volume"] != "minimal" else n_active_stages)
        min_conv = 3 if cdef["volume"] != "minimal" else 2
        while len(leads_by_status["qualificado"]) < min_qual:
            name = self._random_name()
            company = self.rng.choice(client_companies) if self.rng.random() > 0.2 else ""
            lead = Lead.objects.create(
                empresa=empresa, name=name, email=self._random_email(name),
                phone=self._random_phone(), company=company,
                source=self._pick(LEAD_SOURCES, LEAD_SOURCE_WEIGHTS),
                status="qualificado", notes="Cliente qualificado, pronto para proposta.",
                assigned_to=self.rng.choice(assignable_users),
            )
            self._backdate(Lead, lead.pk, self._random_date(90))
            leads_by_status["qualificado"].append(lead)

        while len(leads_by_status["convertido"]) < min_conv:
            name = self._random_name()
            company = self.rng.choice(client_companies) if self.rng.random() > 0.2 else ""
            lead = Lead.objects.create(
                empresa=empresa, name=name, email=self._random_email(name),
                phone=self._random_phone(), company=company,
                source=self._pick(LEAD_SOURCES, LEAD_SOURCE_WEIGHTS),
                status="convertido", notes="Proposta aceita, contrato em elaboracao.",
                assigned_to=self.rng.choice(assignable_users),
            )
            self._backdate(Lead, lead.pk, self._random_date(120))
            leads_by_status["convertido"].append(lead)

        return leads_by_status

    def _lead_notes(self, status, cdef):
        segment = cdef["name"]
        notes_map = {
            "novo": [
                "Entrou em contato pelo site solicitando orcamento.",
                "Indicacao de cliente antigo.",
                "Interessado em nossos servicos.",
                "",
            ],
            "contatado": [
                "Retornamos o contato, aguardando documentacao.",
                "Ligou pedindo mais detalhes sobre prazos.",
                "Enviamos material informativo por e-mail.",
            ],
            "qualificado": [
                "Cliente qualificado, tem budget e prazo definidos.",
                "Projeto com escopo bem definido, pronto para proposta.",
                f"Demanda compativel com os servicos de {segment}.",
            ],
            "convertido": [
                "Cliente fechou contrato, iniciar execucao.",
                "Proposta aceita, contrato em elaboracao.",
            ],
            "perdido": [
                "Cliente optou por concorrente com preco menor.",
                "Projeto cancelado pelo cliente.",
                "Sem retorno apos 3 tentativas de contato.",
                "Budget insuficiente para o escopo solicitado.",
            ],
        }
        return self.rng.choice(notes_map.get(status, [""]))

    def _create_opportunities(self, empresa, leads_by_status, pipeline, stages, users):
        from apps.crm.models import Opportunity

        active_stages = [s for s in stages if not s.is_won and not s.is_lost]
        won_stage = next((s for s in stages if s.is_won), stages[-2])
        lost_stage = next((s for s in stages if s.is_lost), stages[-1])
        assignable = users[:3]

        opportunities = []

        # STEP 1: Guarantee at least 1 opp in EVERY active stage (round-robin)
        qualified_leads = list(leads_by_status.get("qualificado", []))
        self.rng.shuffle(qualified_leads)

        for idx, stage in enumerate(active_stages):
            if not qualified_leads:
                break
            lead = qualified_leads.pop(0)
            value = self._random_value(3000, 40000)
            max_order = max(s.order for s in active_stages)
            prob = int(20 + (stage.order / max(max_order, 1)) * 60) if max_order > 0 else 50

            opp = Opportunity.objects.create(
                empresa=empresa, lead=lead, pipeline=pipeline,
                current_stage=stage,
                title=f"Oportunidade - {lead.company or lead.name}",
                value=value, probability=prob,
                expected_close_date=self._future_date(10, 90),
                priority=self._pick(["low", "medium", "high"], [20, 50, 30]),
                assigned_to=self.rng.choice(assignable),
            )
            self._backdate(Opportunity, opp.pk, self._random_date(120))
            opportunities.append(opp)

        # STEP 2: Remaining qualified leads go to random active stages
        for lead in qualified_leads:
            stage = self.rng.choice(active_stages)
            value = self._random_value(2000, 50000)
            max_order = max(s.order for s in active_stages)
            prob = int(20 + (stage.order / max(max_order, 1)) * 60) if max_order > 0 else 50

            opp = Opportunity.objects.create(
                empresa=empresa, lead=lead, pipeline=pipeline,
                current_stage=stage,
                title=f"Oportunidade - {lead.company or lead.name}",
                value=value, probability=prob,
                expected_close_date=self._future_date(10, 90),
                priority=self._pick(["low", "medium", "high"], [20, 50, 30]),
                assigned_to=self.rng.choice(assignable) if self.rng.random() > 0.2 else None,
            )
            self._backdate(Opportunity, opp.pk, self._random_date(120))
            opportunities.append(opp)

        # STEP 3: Won opportunities for converted leads
        for lead in leads_by_status.get("convertido", []):
            value = self._random_value(5000, 60000)
            won_dt = self._random_datetime(90)
            opp = Opportunity.objects.create(
                empresa=empresa, lead=lead, pipeline=pipeline,
                current_stage=won_stage,
                title=f"Oportunidade - {lead.company or lead.name}",
                value=value, probability=100,
                expected_close_date=won_dt.date(),
                priority=self._pick(["low", "medium", "high"], [15, 45, 40]),
                assigned_to=self.rng.choice(assignable) if self.rng.random() > 0.1 else None,
                won_at=won_dt,
            )
            self._backdate(Opportunity, opp.pk, won_dt - timedelta(days=self.rng.randint(15, 60)))
            opportunities.append(opp)

        # STEP 4: Lost opportunities for some lost leads
        lost_leads = leads_by_status.get("perdido", [])
        for lead in lost_leads[:max(1, len(lost_leads) // 2)]:
            lost_dt = self._random_datetime(120)
            lost_reasons = [
                "Cliente optou por concorrente",
                "Projeto cancelado",
                "Budget insuficiente",
                "Sem retorno do cliente",
            ]
            opp = Opportunity.objects.create(
                empresa=empresa, lead=lead, pipeline=pipeline,
                current_stage=lost_stage,
                title=f"Oportunidade - {lead.company or lead.name}",
                value=self._random_value(3000, 30000), probability=0,
                priority="medium",
                assigned_to=self.rng.choice(assignable) if self.rng.random() > 0.3 else None,
                lost_at=lost_dt,
                lost_reason=self.rng.choice(lost_reasons),
            )
            self._backdate(Opportunity, opp.pk, lost_dt - timedelta(days=self.rng.randint(10, 45)))
            opportunities.append(opp)

        return opportunities

    def _create_proposals(self, empresa, leads_by_status, opportunities, cdef, count):
        from apps.proposals.models import Proposal, ProposalItem, ProposalTemplate

        statuses = ["draft", "sent", "viewed", "accepted", "rejected", "expired"]
        status_weights = [15, 15, 10, 35, 15, 10]
        templates = list(ProposalTemplate.objects.filter(empresa=empresa))
        item_defs = cdef["proposal_items"]

        # Quantity ranges per unit (realistic, not astronomical)
        qty_ranges = {
            "un": [1, 1, 2, 3],
            "m\u00b2": [20, 50, 80, 120, 200],
            "ha": [2, 5, 10, 20],
            "km": [1, 2, 5, 10],
            "km\u00b2": [1, 2, 5],
            "ponto": [5, 10, 15, 20, 30],
            "mes": [1, 2, 3, 6],
            "turma": [1, 2],
        }

        # Leads that can have proposals
        eligible_leads = (
            leads_by_status.get("qualificado", [])
            + leads_by_status.get("convertido", [])
            + leads_by_status.get("contatado", [])[:3]
        )
        if not eligible_leads:
            return []

        proposals = []
        for i in range(count):
            lead = self.rng.choice(eligible_leads)
            status = self._pick(statuses, status_weights)
            created = self._random_date(150)
            discount = self._pick([Decimal("0"), Decimal("5"), Decimal("10"), Decimal("15")],
                                  [40, 30, 20, 10])

            # Find matching opportunity if exists
            matching_opps = [o for o in opportunities if o.lead_id == lead.pk]
            opportunity = matching_opps[0] if matching_opps and self.rng.random() > 0.3 else None

            payment_method = self._pick(
                ["pix", "boleto", "cartao_credito", "transferencia", "dinheiro", ""],
                [25, 25, 20, 15, 5, 10],
            )
            is_installment = self.rng.random() < 0.4
            installment_count = self.rng.choice([2, 3, 4, 6, 12]) if is_installment else None

            prop = Proposal.objects.create(
                empresa=empresa,
                lead=lead,
                opportunity=opportunity,
                template=self.rng.choice(templates) if templates and self.rng.random() > 0.3 else None,
                title=f"Proposta para {lead.company or lead.name}",
                introduction=f"Prezado(a) {lead.name.split()[0]}, apresentamos nossa proposta conforme solicitado.",
                terms="Validade: 30 dias. Pagamento: conforme negociacao.",
                status=status,
                discount_percent=discount,
                payment_method=payment_method,
                is_installment=is_installment,
                installment_count=installment_count,
                valid_until=created + timedelta(days=30) if status != "expired" else self._past_date(5, 30),
                sent_at=self._random_datetime(120) if status in ("sent", "viewed", "accepted", "rejected") else None,
                accepted_at=self._random_datetime(90) if status == "accepted" else None,
                rejected_at=self._random_datetime(90) if status == "rejected" else None,
            )
            self._backdate(Proposal, prop.pk, created)

            # Create proposal items with REALISTIC quantities
            n_items = self.rng.randint(2, min(5, len(item_defs)))
            selected_items = self.rng.sample(item_defs, n_items)
            for order, (desc, unit, min_p, max_p) in enumerate(selected_items):
                choices = qty_ranges.get(unit, [1, 2, 3])
                qty = Decimal(str(self.rng.choice(choices)))
                ProposalItem.objects.create(
                    proposal=prop,
                    description=desc,
                    quantity=qty,
                    unit=unit,
                    unit_price=self._random_value(min_p, max_p),
                    order=order,
                )

            prop.recalculate_totals()
            proposals.append(prop)

        return proposals

    def _create_contracts(self, empresa, leads_by_status, proposals, cdef, count):
        from apps.contracts.models import Contract, ContractTemplate

        statuses = ["draft", "sent", "signed", "active", "completed", "cancelled"]
        status_weights = [15, 10, 15, 30, 20, 10]
        templates = list(ContractTemplate.objects.filter(empresa=empresa))

        # Accepted proposals get contracts FIRST (high priority linking)
        accepted = list(reversed([p for p in proposals if p.status == "accepted"]))
        other_leads = leads_by_status.get("convertido", []) + leads_by_status.get("qualificado", [])[:3]

        contracts = []
        for i in range(count):
            status = self._pick(statuses, status_weights)
            created = self._random_date(120)

            # Link to accepted proposal with high probability
            prop = None
            if accepted:
                prop = accepted.pop()
            elif self.rng.random() > 0.7 and proposals:
                # Occasionally link to sent/viewed proposals too
                non_draft = [p for p in proposals if p.status in ("sent", "viewed")]
                if non_draft:
                    prop = self.rng.choice(non_draft)

            lead = prop.lead if prop else (self.rng.choice(other_leads) if other_leads else None)
            if not lead:
                continue

            value = prop.total if prop else self._random_value(3000, 60000)
            title = f"Contrato - {lead.company or lead.name}"

            start_d = created + timedelta(days=self.rng.randint(5, 30))
            end_d = start_d + timedelta(days=self.rng.randint(30, 180))

            contract = Contract.objects.create(
                empresa=empresa,
                proposal=prop,
                lead=lead,
                template=self.rng.choice(templates) if templates else None,
                title=title,
                content=f"Contrato de prestacao de servicos para {lead.company or lead.name}.",
                value=value,
                status=status,
                start_date=start_d if status in ("signed", "active", "completed") else None,
                end_date=end_d if status in ("signed", "active", "completed") else None,
                signed_at=self._random_datetime(90) if status in ("signed", "active", "completed") else None,
                notes=f"Contrato referente a proposta {prop.number}" if prop else "",
            )
            self._backdate(Contract, contract.pk, created)
            contracts.append(contract)

        return contracts

    def _create_work_orders(self, empresa, leads_by_status, proposals, contracts,
                            service_types, checklist_templates, users, teams, cdef, count):
        from apps.operations.models import WorkOrder, WorkOrderChecklist

        # Explicit counts per status for better distribution
        status_plan = self._plan_status_counts(count, {
            "pending": 0.12, "scheduled": 0.18, "in_progress": 0.22,
            "on_hold": 0.05, "completed": 0.35, "cancelled": 0.08,
        })
        priorities = ["low", "medium", "high"]
        priority_weights = [20, 50, 30]
        tech_users = [u for u in users if u.email.startswith("tecnico")]
        assignable = tech_users + users[:2]  # tecnico + admin + comercial

        all_leads = []
        for status_leads in leads_by_status.values():
            all_leads.extend(status_leads)

        # Build a queue of contracts and proposals to link
        contract_queue = list(contracts)
        self.rng.shuffle(contract_queue)
        proposal_queue = list(proposals)
        self.rng.shuffle(proposal_queue)

        work_orders = []
        for status, n in status_plan:
            for _ in range(n):
                priority = self._pick(priorities, priority_weights)
                created = self._random_date(150)

                # Smart linking: prefer contract > proposal > lead
                contract = None
                proposal = None
                lead = None

                if contract_queue and self.rng.random() > 0.35:
                    contract = contract_queue.pop() if contract_queue else None
                    if contract:
                        lead = contract.lead
                        proposal = contract.proposal

                if not lead and proposal_queue and self.rng.random() > 0.3:
                    proposal = proposal_queue.pop() if proposal_queue else None
                    if proposal:
                        lead = proposal.lead

                if not lead and all_leads:
                    lead = self.rng.choice(all_leads)

                st = self.rng.choice(service_types) if service_types else None
                title = f"{st.name} - {lead.company or lead.name}" if st and lead else f"Ordem de Servico #{len(work_orders) + 1}"

                # Date logic based on status
                if status == "completed":
                    sched_date = self._past_date(5, 90)
                    completed_at = timezone.make_aware(
                        timezone.datetime(sched_date.year, sched_date.month, sched_date.day, 17, 0)
                    )
                elif status == "scheduled":
                    # 60% future, 40% overdue (past)
                    if self.rng.random() > 0.4:
                        sched_date = self._future_date(1, 45)
                    else:
                        sched_date = self._past_date(1, 14)
                    completed_at = None
                elif status == "pending":
                    # Pending: some with date, some without
                    if self.rng.random() > 0.4:
                        sched_date = self._future_date(3, 30)
                    else:
                        sched_date = None
                    completed_at = None
                elif status == "in_progress":
                    sched_date = self._past_date(1, 10)
                    completed_at = None
                else:  # on_hold, cancelled
                    sched_date = self._future_date(5, 60) if self.rng.random() > 0.5 else None
                    completed_at = None

                sched_time = time(self.rng.randint(7, 16), self.rng.choice([0, 30])) if sched_date else None

                location = self.rng.choice(ALL_LOCATIONS) if self.rng.random() > 0.25 else ""

                # Google Maps URL: 70% manual quando tem location, 30% vazio (testa auto-geração)
                maps_url = ""
                if location and self.rng.random() > 0.3:
                    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(location)}"

                # Cloud storage links: ~40% das OS
                cloud_links = []
                if self.rng.random() < 0.4:
                    link_options = [
                        {"label": "Projeto Técnico", "url": "https://drive.google.com/drive/folders/example-projeto"},
                        {"label": "Fotos do Local", "url": "https://drive.google.com/drive/folders/example-fotos"},
                        {"label": "Laudo de Vistoria", "url": "https://dropbox.com/s/example-laudo/laudo.pdf"},
                        {"label": "Planta Baixa", "url": "https://drive.google.com/file/d/example-planta"},
                        {"label": "Orçamento Detalhado", "url": "https://docs.google.com/spreadsheets/d/example-orcamento"},
                        {"label": "Relatório de Campo", "url": "https://dropbox.com/s/example-relatorio/campo.pdf"},
                        {"label": "Documentação do Cliente", "url": "https://onedrive.live.com/example-docs"},
                    ]
                    n_links = self.rng.randint(1, 3)
                    cloud_links = self.rng.sample(link_options, min(n_links, len(link_options)))

                wo = WorkOrder.objects.create(
                    empresa=empresa,
                    title=title,
                    lead=lead,
                    proposal=proposal,
                    contract=contract,
                    service_type=st,
                    status=status,
                    priority=priority,
                    description=f"Execucao de {st.name.lower() if st else 'servico'} conforme escopo definido.",
                    scheduled_date=sched_date,
                    scheduled_time=sched_time,
                    completed_at=completed_at,
                    assigned_to=self.rng.choice(assignable) if assignable and self.rng.random() > 0.1 else None,
                    assigned_team=self.rng.choice(teams) if teams and self.rng.random() > 0.5 else None,
                    location=location,
                    google_maps_url=maps_url,
                    cloud_storage_links=cloud_links,
                )
                self._backdate(WorkOrder, wo.pk, created)

                # Create checklist items from templates
                if checklist_templates:
                    tmpl = self.rng.choice(checklist_templates)
                    tmpl_items = list(tmpl.items.all())
                    for ci in tmpl_items:
                        is_done = False
                        done_at = None
                        if status == "completed":
                            is_done = True
                            done_at = completed_at
                        elif status == "in_progress":
                            is_done = self.rng.random() > 0.4
                            if is_done:
                                done_at = self._random_datetime(10)

                        WorkOrderChecklist.objects.create(
                            work_order=wo,
                            description=ci.description,
                            is_completed=is_done,
                            completed_at=done_at,
                            order=ci.order,
                        )

                work_orders.append(wo)

        return work_orders

    def _plan_status_counts(self, total, distribution):
        """Turn a {status: pct} dict into [(status, count)] ensuring sum == total."""
        result = []
        remaining = total
        items = list(distribution.items())
        for i, (status, pct) in enumerate(items):
            if i == len(items) - 1:
                n = remaining
            else:
                n = round(total * pct)
                n = min(n, remaining)
            result.append((status, n))
            remaining -= n
        return result

    def _create_financial_entries(self, empresa, proposals, contracts, work_orders,
                                 categories, bank_accounts, cdef, count):
        from apps.finance.models import FinancialEntry
        from apps.finance.services import generate_entries_from_proposal

        income_cats = categories.get("income", [])
        expense_cats = categories.get("expense", [])
        default_bank = bank_accounts[0] if bank_accounts else None

        accepted_proposals = [p for p in proposals if p.status == "accepted"]
        active_contracts = [c for c in contracts if c.status in ("active", "completed", "signed")]

        # Gera automaticamente entries a partir das propostas aceitas (idempotente).
        # Respeita is_installment / installment_count definidos na proposta.
        auto_entries_created = 0
        for prop in accepted_proposals:
            base_date = prop.accepted_at.date() if prop.accepted_at else self._random_date(90)
            try:
                created = generate_entries_from_proposal(prop, first_due_date=base_date)
                auto_entries_created += len(created)
                # Marca algumas como pagas para realismo
                for entry in created:
                    if self.rng.random() < 0.4:
                        entry.status = "paid"
                        entry.paid_date = entry.date + timedelta(days=self.rng.randint(0, 5))
                        entry.save(update_fields=["status", "paid_date"])
                    # Atribui categoria de receita se disponível
                    if income_cats and not entry.category_id:
                        entry.category = self.rng.choice(income_cats)
                        entry.save(update_fields=["category"])
            except Exception:
                pass

        # Calcula contagem restante para manter volume total similar ao solicitado
        remaining = max(0, count - auto_entries_created)
        n_income = int(remaining * 0.35)
        n_expense = remaining - n_income

        # Income entries
        for i in range(n_income):
            date = self._random_date(150)
            status = self._pick(["paid", "pending", "overdue", "cancelled"], [45, 25, 20, 10])

            # Link some to proposals/contracts
            rel_prop = None
            rel_cont = None
            if accepted_proposals and self.rng.random() > 0.5:
                rel_prop = self.rng.choice(accepted_proposals)
                # Cap income at realistic values based on proposal total
                fraction = Decimal(str(self.rng.choice([1, 2, 3])))
                amount = min(rel_prop.total / fraction, Decimal("50000"))
                desc = f"Recebimento - {rel_prop.title}"
            elif active_contracts and self.rng.random() > 0.4:
                rel_cont = self.rng.choice(active_contracts)
                fraction = Decimal(str(self.rng.choice([1, 2, 3, 4])))
                amount = min(rel_cont.value / fraction, Decimal("50000"))
                desc = f"Parcela - {rel_cont.title}"
            else:
                amount = self._random_value(500, 15000)
                desc = self.rng.choice([
                    "Recebimento de servico avulso",
                    "Pagamento de cliente",
                    "Entrada de contrato",
                    "Recebimento parcial",
                    "Faturamento mensal",
                ])

            paid_date = None
            if status == "paid":
                paid_date = date + timedelta(days=self.rng.randint(0, 5))
            elif status == "overdue":
                date = self._past_date(15, 60)

            FinancialEntry.objects.create(
                empresa=empresa,
                type="income",
                description=desc,
                amount=amount.quantize(Decimal("0.01")),
                category=self.rng.choice(income_cats) if income_cats else None,
                date=date,
                paid_date=paid_date,
                status=status,
                related_proposal=rel_prop,
                related_contract=rel_cont,
                bank_account=default_bank if self.rng.random() > 0.2 else None,
                notes="",
            )

        # Expense entries
        expense_descs = [
            "Salario mensal", "Aluguel do escritorio", "Conta de energia",
            "Conta de internet", "Material de escritorio", "Combustivel",
            "Manutencao de equipamento", "Software e licencas",
            "Imposto mensal", "Contador", "Seguro empresarial",
            "Marketing digital", "Telefone corporativo",
        ]

        for i in range(n_expense):
            date = self._random_date(150)
            status = self._pick(["paid", "pending", "overdue", "cancelled"], [50, 25, 15, 10])

            desc = self.rng.choice(expense_descs)
            amount = self._random_value(100, 5000)

            # Some expenses linked to work orders
            rel_wo = None
            if work_orders and self.rng.random() > 0.7:
                rel_wo = self.rng.choice(work_orders)
                desc = f"Custo operacional - {rel_wo.title[:40]}"
                amount = self._random_value(150, 2500)

            paid_date = None
            if status == "paid":
                paid_date = date + timedelta(days=self.rng.randint(0, 3))
            elif status == "overdue":
                date = self._past_date(15, 60)

            FinancialEntry.objects.create(
                empresa=empresa,
                type="expense",
                description=desc,
                amount=amount.quantize(Decimal("0.01")),
                category=self.rng.choice(expense_cats) if expense_cats else None,
                date=date,
                paid_date=paid_date,
                status=status,
                related_work_order=rel_wo,
                bank_account=self.rng.choice(bank_accounts) if bank_accounts and self.rng.random() > 0.3 else None,
                notes="",
            )

        # Ensure entries in the current month for dashboard richness
        month_start = self.today.replace(day=1)
        current_month_entries = FinancialEntry.objects.filter(
            empresa=empresa, date__gte=month_start
        ).count()

        needed = max(0, 8 - current_month_entries)
        for j in range(needed):
            day_offset = self.rng.randint(0, min(self.today.day - 1, 25))
            entry_date = month_start + timedelta(days=day_offset)
            entry_type = "income" if j % 2 == 0 else "expense"
            cats = income_cats if entry_type == "income" else expense_cats
            is_paid = self.rng.random() > 0.25
            FinancialEntry.objects.create(
                empresa=empresa,
                type=entry_type,
                description=self.rng.choice([
                    "Recebimento de servico", "Pagamento de cliente", "Faturamento",
                ]) if entry_type == "income" else self.rng.choice(expense_descs),
                amount=self._random_value(800, 8000).quantize(Decimal("0.01")),
                category=self.rng.choice(cats) if cats else None,
                date=entry_date,
                paid_date=entry_date if is_paid else None,
                status="paid" if is_paid else "pending",
                bank_account=default_bank if self.rng.random() > 0.25 else None,
            )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== RESUMO DO SEED ===\n"))
        self.stdout.write(
            f"{'Empresa':<30} | {'Leads':>5} | {'Prop.':>5} | {'Cont.':>5} | {'OS':>5} | {'Fin.':>5}"
        )
        self.stdout.write("-" * 75)

        total = {"leads": 0, "proposals": 0, "contracts": 0, "work_orders": 0, "entries": 0}
        for name, vol in self.counters.items():
            self.stdout.write(
                f"{name:<30} | {vol['leads']:>5} | {vol['proposals']:>5} | "
                f"{vol['contracts']:>5} | {vol['work_orders']:>5} | {vol['entries']:>5}"
            )
            for k in total:
                total[k] += vol[k]

        self.stdout.write("-" * 75)
        self.stdout.write(
            f"{'TOTAL':<30} | {total['leads']:>5} | {total['proposals']:>5} | "
            f"{total['contracts']:>5} | {total['work_orders']:>5} | {total['entries']:>5}"
        )

        self.stdout.write(self.style.SUCCESS("\n[OK] Seed concluido com sucesso!"))
        self.stdout.write("\nAcessos demo (senha: Demo123!):")
        from apps.accounts.models import User
        for user in User.objects.filter(email__startswith="admin@", email__endswith=".demo").order_by("email"):
            self.stdout.write(f"  {user.full_name}: {user.email}")

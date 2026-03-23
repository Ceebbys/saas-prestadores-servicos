# Guia de Testes e Demonstracao - Base Demo

> Senha universal: **`Demo123!`**
> Servidor: `python manage.py runserver` -> `http://localhost:8000`

---

## Logins Disponiveis

### GeoPrime Topografia (volume pesado, 40 leads)
| Email | Nome | Papel |
|-------|------|-------|
| `admin@geoprime-topografia.demo` | Ricardo Mendes | Proprietario |
| `comercial@geoprime-topografia.demo` | Camila Torres | Gerente |
| `tecnico@geoprime-topografia.demo` | Bruno Almeida | Membro |
| `financeiro@geoprime-topografia.demo` | Fernanda Costa | Membro |

### Studio Alto Arquitetura (volume padrao, 28 leads)
| Email | Nome | Papel |
|-------|------|-------|
| `admin@studio-alto-arquitetura.demo` | Mariana Lopes | Proprietario |
| `comercial@studio-alto-arquitetura.demo` | Gabriel Oliveira | Gerente |
| `tecnico@studio-alto-arquitetura.demo` | Juliana Ferreira | Membro |
| `financeiro@studio-alto-arquitetura.demo` | Paulo Ribeiro | Membro |

### Alfa Assistencia Tecnica (volume padrao, 28 leads)
| Email | Nome | Papel |
|-------|------|-------|
| `admin@alfa-assistencia-tecnica.demo` | Antonio Vieira | Proprietario |
| `comercial@alfa-assistencia-tecnica.demo` | Luciana Cardoso | Gerente |
| `tecnico@alfa-assistencia-tecnica.demo` | Marcio Nunes | Membro |
| `financeiro@alfa-assistencia-tecnica.demo` | Debora Freitas | Membro |

### Campo Forte Consultoria (volume minimo, 19 leads)
| Email | Nome | Papel |
|-------|------|-------|
| `admin@campo-forte-consultoria.demo` | Helena Martins | Proprietario |
| `comercial@campo-forte-consultoria.demo` | Renato Barbosa | Gerente |
| `tecnico@campo-forte-consultoria.demo` | Cintia Araujo | Membro |
| `financeiro@campo-forte-consultoria.demo` | Fabio Teixeira | Membro |

### Luz & Instalacoes (volume padrao, 28 leads)
| Email | Nome | Papel |
|-------|------|-------|
| `admin@luz-instalacoes.demo` | Sergio Rocha | Proprietario |
| `comercial@luz-instalacoes.demo` | Viviane Dias | Gerente |
| `tecnico@luz-instalacoes.demo` | Anderson Moreira | Membro |
| `financeiro@luz-instalacoes.demo` | Patricia Gomes | Membro |

---

## O Que Testar em Cada Conta

### GeoPrime Topografia
- **Dashboard rico**: R$17k receita, R$4k despesa no mes, 9 inadimplentes
- **Listas paginadas**: 40 leads (2 paginas de 20)
- **Pipeline populado**: 6 etapas todas com oportunidades, 9 ganhas, 3 perdidas
- **20 propostas**: 8 aceitas, 5 rascunho, 4 visualizadas, 2 enviadas, 1 expirada
- **15 contratos**: 5 assinados, 5 concluidos, 3 ativos, 11 vinculados a propostas
- **25 OS**: 9 concluidas, 6 em andamento, 4 agendadas, 2 atrasadas, 161 itens de checklist
- **Filtros**: testar busca por nome, filtro por status, filtro por origem nos leads
- **Servicos**: Levantamento Planialtimetrico, Georreferenciamento, Locacao de Obra, Drone, Cadastro de Redes

### Studio Alto Arquitetura
- **Pipeline mais longo**: 7 etapas (Contato -> Briefing -> Estudo -> Anteprojeto -> Executivo -> Ganho/Perdido)
- **Todas as etapas com 2-3 oportunidades**: pipeline visualmente equilibrado
- **Propostas com m2**: itens por metro quadrado (R$30-120/m2), valores entre R$10k-R$65k
- **Contratos diversificados**: rascunho, enviado, ativo, cancelado
- **Dashboard expressivo**: R$35k receita no mes, 12 inadimplentes
- **Servicos**: Projeto Residencial, Comercial, Interiores, Reforma, Regularizacao

### Alfa Assistencia Tecnica
- **Fluxo de manutencao**: Solicitacao -> Visita -> Orcamento -> Reparo -> Finalizacao
- **Propostas de baixo valor**: R$1k-R$10k (compativel com reparos e manutencao)
- **6 oportunidades ganhas**: volume alto de conversao
- **OS com checklists tecnicos**: "Verificar tensao e corrente", "Fotografar componentes"
- **Despesas altas no mes**: R$13k (pecas, deslocamento) vs R$7k receita
- **Servicos**: Manutencao Preventiva/Corretiva, Instalacao, Visita Tecnica, Troca de Pecas

### Campo Forte Consultoria
- **Empresa enxuta**: dados minimos para testar visual com poucas informacoes
- **Listas sem paginacao**: 19 leads, 8 propostas, 5 contratos, 8 OS
- **Propostas de alto valor unitario**: R$20k-R$79k (consultorias e diagnosticos)
- **Todos contratos vinculados a propostas**: 5/5 (100%)
- **Pipeline completo mas discreto**: 1 oportunidade por etapa ativa
- **Servicos**: Diagnostico Organizacional, Consultoria Estrategica, Treinamento, Auditoria

### Luz & Instalacoes
- **Pipeline mais extenso**: 8 etapas (Contato -> Vistoria -> Orcamento -> Instalacao -> Testes -> Entrega -> Ganho/Perdido)
- **Propostas por ponto/unidade**: itens como "ponto eletrico" a R$80-200/ponto
- **6 tipos de servico**: maior catalogo de servicos entre as empresas
- **2 checklists detalhados**: "Vistoria Eletrica" (6 itens) e "Instalacao Completa" (8 itens)
- **Valores moderados**: propostas de R$2k-R$16k
- **Servicos**: Instalacao Residencial/Comercial, Quadro de Distribuicao, Luminarias, Laudo NR-10, Manutencao

---

## Funcionalidades do Nucleo Fixo

Estas funcionalidades existem em TODAS as empresas e podem ser testadas em qualquer conta:

### CRM
- [ ] Lista de leads com filtro por status (novo/contatado/qualificado/perdido/convertido)
- [ ] Lista de leads com filtro por origem (site/indicacao/google/instagram/telefone/outro)
- [ ] Busca de leads por nome, email ou empresa
- [ ] Detalhe do lead com dados completos e historico
- [ ] Criar/editar/excluir lead
- [ ] Pipeline Kanban com cards arrastados entre colunas
- [ ] Detalhe da oportunidade com valor, probabilidade e responsavel
- [ ] Mover oportunidade entre etapas

### Propostas
- [ ] Lista de propostas com filtro por status
- [ ] Busca por numero ou titulo
- [ ] Detalhe da proposta com itens, subtotal, desconto e total
- [ ] Itens com descricao, quantidade, unidade e preco unitario
- [ ] Badges de status (rascunho, enviada, visualizada, aceita, rejeitada, expirada)
- [ ] Criar proposta vinculada a lead/oportunidade

### Contratos
- [ ] Lista de contratos com filtro por status
- [ ] Detalhe do contrato com valor, datas e vinculo com proposta
- [ ] Badges de status (rascunho, enviado, assinado, ativo, concluido, cancelado)
- [ ] Criar contrato a partir de proposta aceita

### Ordens de Servico
- [ ] Lista de OS com filtro por status, prioridade e responsavel
- [ ] Detalhe da OS com checklist interativo (toggle de itens)
- [ ] OS com data agendada, tipo de servico e localizacao
- [ ] Calendario de OS agendadas
- [ ] Badges de prioridade (baixa, media, alta)

### Financeiro
- [ ] Visao geral com receitas, despesas e saldo do mes
- [ ] Lista de lancamentos com filtro por tipo, status, categoria e periodo
- [ ] Lancamentos vinculados a propostas, contratos ou OS
- [ ] Marcar lancamento como pago
- [ ] Contagem de inadimplentes no dashboard

### Dashboard
- [ ] Total de leads e novos no mes
- [ ] Propostas abertas e aceitas com valor total
- [ ] OS pendentes e em andamento
- [ ] Receita, despesa, saldo e inadimplencia do mes
- [ ] Leads recentes (5 ultimos)
- [ ] OS agendadas proximas
- [ ] Resumo do pipeline com contagem e valores por etapa

---

## Funcionalidades da Camada Flexivel

Estas variam por empresa e demonstram a adaptabilidade do sistema:

### Pipeline Configuravel
| Empresa | Etapas | Fluxo |
|---------|:------:|-------|
| GeoPrime | 6 | Primeiro Contato -> Levantamento -> Processamento -> Entrega |
| Studio Alto | 7 | Contato -> Briefing -> Estudo -> Anteprojeto -> Executivo |
| Alfa | 7 | Solicitacao -> Visita -> Orcamento -> Reparo -> Finalizacao |
| Campo Forte | 7 | Prospeccao -> Diagnostico -> Proposta -> Plano de Acao -> Entrega |
| Luz | 8 | Contato -> Vistoria -> Orcamento -> Instalacao -> Testes -> Entrega |

**Como testar**: login em 2-3 empresas diferentes e navegar ate o Pipeline. Notar como as
colunas mudam de nome e quantidade conforme o segmento.

### Tipos de Servico por Segmento
- **Topografia**: Levantamento, Georreferenciamento, Locacao, Drone, Cadastro
- **Arquitetura**: Residencial, Comercial, Interiores, Reforma, Regularizacao
- **Manutencao**: Preventiva, Corretiva, Instalacao, Visita, Troca de Pecas
- **Consultoria**: Diagnostico, Estrategica, Treinamento, Auditoria
- **Eletrica**: Residencial, Comercial, Quadro, Luminarias, Laudo NR-10, Manutencao

**Como testar**: abrir uma OS em cada empresa e verificar os tipos de servico disponiveis
no formulario. Navegar ate Configuracoes > Tipos de Servico.

### Templates de Proposta e Contrato
Cada empresa tem templates com linguagem do seu segmento. Verificar em Configuracoes.

### Checklists por Segmento
- **Topografia**: "Verificar calibracao do equipamento", "Coletar dados GNSS"
- **Arquitetura**: "Fotografar o terreno", "Verificar orientacao solar"
- **Manutencao**: "Testar funcionamento atual", "Verificar tensao e corrente"
- **Consultoria**: "Entrevistar gestores-chave", "Mapear processos atuais"
- **Eletrica**: "Verificar disjuntores", "Medir resistencia de aterramento"

**Como testar**: abrir uma OS concluida e ver o checklist 100% preenchido. Abrir uma
OS em andamento e ver o checklist parcialmente preenchido.

### Categorias Financeiras
Alem das 10 categorias padrao, cada empresa tem categorias extras do segmento:
- **Topografia**: Equipamentos, Combustivel, Diarias de Campo, Levantamentos, Licencas de Software
- **Arquitetura**: Renderizacao 3D, Plotagem, Projetos Arquitetonicos
- **Manutencao**: Pecas e Componentes, Ferramentas, Manutencoes
- **Consultoria**: Viagens, Hospedagem, Consultorias
- **Eletrica**: Material Eletrico, Ferramentas e EPIs, Instalacoes

**Como testar**: criar um lancamento financeiro e verificar as categorias disponiveis no
dropdown. Navegar ate Configuracoes > Categorias Financeiras.

---

## Demonstracao em 5 Minutos

> Conta recomendada: `admin@geoprime-topografia.demo`

### 1. Dashboard (30s)
- Login -> Dashboard abre automaticamente
- Mostrar os cards: leads, propostas, OS, financeiro
- Destacar saldo do mes e inadimplencia
- Mostrar pipeline resumido com valores por etapa

### 2. CRM - Leads (60s)
- Clicar em "Leads" na sidebar
- Mostrar lista com 40 leads (2 paginas)
- Filtrar por status "Qualificado" -> mostrar os leads prontos para proposta
- Clicar em um lead -> mostrar detalhe com dados e historico

### 3. Pipeline (60s)
- Clicar em "Pipeline" na sidebar
- Mostrar board Kanban com 6 colunas
- Apontar oportunidades em diferentes etapas com valores
- Mostrar coluna "Fechado/Ganho" com 9 oportunidades

### 4. Propostas (60s)
- Clicar em "Propostas" na sidebar
- Mostrar lista com badges de status variados
- Abrir uma proposta aceita -> mostrar itens, quantidades, precos, total
- Destacar desconto aplicado e valor final

### 5. Financeiro (60s)
- Clicar em "Financeiro" na sidebar
- Mostrar visao geral: receita vs despesa
- Abrir lista de lancamentos
- Filtrar por "Vencido" -> mostrar inadimplentes
- Mostrar vinculo de lancamento com proposta ou contrato

### Fechamento (30s)
- Voltar ao Dashboard
- Destacar que tudo e multi-tenant: cada empresa ve so seus dados
- Mencionar que pipeline, servicos, templates e categorias sao configuraveis

---

## Demonstracao em 15 Minutos

> Usar 3 contas para demonstrar multi-tenancy e flexibilidade

### Parte 1: GeoPrime Topografia (5min)

**Dashboard e CRM (2min)**
- Login com `admin@geoprime-topografia.demo`
- Dashboard: mostrar metricas com volume real
- Leads: filtrar por status, buscar por nome, mostrar paginacao (pagina 2)
- Abrir lead qualificado -> ver dados completos

**Pipeline e Oportunidades (1.5min)**
- Pipeline Kanban com 6 colunas todas populadas
- Clicar em uma oportunidade -> ver valor, probabilidade, lead vinculado
- Mostrar oportunidades ganhas (9) e perdidas (3)

**Propostas e Contratos (1.5min)**
- Lista de propostas: mostrar mix de status (rascunho, enviada, aceita)
- Abrir proposta aceita: itens de topografia (levantamento, georreferenciamento)
- Mostrar contrato vinculado a proposta aceita
- Destacar numeracao automatica (PROP-2026-XXXX, CONT-2026-XXXX)

### Parte 2: Studio Alto Arquitetura (4min)

**Comparar Pipeline (1min)**
- Login com `admin@studio-alto-arquitetura.demo`
- Pipeline: 7 etapas (Contato -> Briefing -> Estudo -> Anteprojeto -> Executivo)
- Destacar que e DIFERENTE do GeoPrime: cada empresa configura seu fluxo

**Propostas por m2 (1.5min)**
- Abrir proposta com itens por metro quadrado
- Mostrar valores diferentes: projeto executivo a R$50-120/m2
- Comparar com GeoPrime que usa "un" e "ha"

**Configuracoes (1.5min)**
- Navegar ate Configuracoes
- Mostrar tipos de servico: Projeto Residencial, Comercial, Interiores...
- Mostrar templates de proposta com conteudo do segmento
- Mostrar categorias financeiras especificas: Renderizacao 3D, Plotagem

### Parte 3: Alfa Assistencia Tecnica (3min)

**Ordens de Servico (2min)**
- Login com `admin@alfa-assistencia-tecnica.demo`
- Lista de OS: filtrar por "Em Andamento" -> 4 OS
- Abrir OS em andamento: ver checklist parcialmente preenchido
  - "Identificar modelo e serie" -> marcado
  - "Listar pecas necessarias" -> pendente
- Abrir OS concluida: ver checklist 100% completo
- Calendario: mostrar OS agendadas no mes

**Financeiro Detalhado (1min)**
- Visao geral: despesas (R$13k) maiores que receita (R$7k) no mes
- Mostrar lancamentos vinculados a OS
- Filtrar por categoria "Pecas e Componentes" -> custos operacionais

### Parte 4: Contraste Final (3min)

**Campo Forte - Empresa Enxuta (1.5min)**
- Login com `admin@campo-forte-consultoria.demo`
- Dashboard com poucos dados mas funcional
- Pipeline com 1 oportunidade por etapa: visual limpo
- Propostas de alto valor unitario (R$20k-R$79k): consultoria e diferente
- Demonstrar que o sistema funciona bem com pouco ou muito volume

**Luz & Instalacoes - Pipeline Extenso (1.5min)**
- Login com `admin@luz-instalacoes.demo`
- Pipeline com 8 etapas: o mais longo
- 6 tipos de servico: maior catalogo
- Checklist de "Instalacao Completa" com 8 itens detalhados
- Propostas por "ponto" eletrico: unidade de medida diferente

### Fechamento (1min)
- 5 empresas, 5 segmentos, 5 pipelines diferentes
- Mesmo sistema, contextos completamente distintos
- Multi-tenant: cada usuario ve apenas os dados da sua empresa
- Configuravel: pipeline, servicos, templates, categorias, checklists
- Pronto para qualquer prestador de servico

---

## Cenarios Especiais para Teste

### Testar HTMX
- **Filtros em tempo real**: na lista de leads, alterar filtro de status -> tabela atualiza sem reload
- **Checklist toggle**: na OS em andamento, marcar/desmarcar item -> estado salva via HTMX
- **Marcar como pago**: no financeiro, clicar "Marcar como pago" -> status atualiza inline

### Testar Badges e Cards
- **Leads**: badges de status (Novo=azul, Qualificado=amarelo, Convertido=verde, Perdido=vermelho)
- **Propostas**: badges (Rascunho, Enviada, Aceita=verde, Rejeitada=vermelho, Expirada)
- **OS**: badges de prioridade (Baixa, Media, Alta) + status
- **Pipeline**: cards com valor em reais e probabilidade percentual

### Testar Paginacao
- GeoPrime leads: 40 leads, 20 por pagina -> verificar navegacao de paginas
- GeoPrime financeiro: 40+ lancamentos, 25 por pagina

### Testar Empty States
- Criar um novo lead e nao vincular proposta -> detalhe do lead mostra "Nenhuma proposta"
- Filtrar leads por combinacao rara (ex: status=Perdido + origem=Instagram) -> pode retornar vazio

### Testar Fluxo Completo (Lead -> Receita)
1. Na GeoPrime, abrir um lead **Convertido**
2. Ver oportunidade vinculada na etapa **Fechado/Ganho**
3. Ver proposta **Aceita** vinculada ao lead
4. Ver contrato **Ativo** vinculado a proposta
5. Ver OS vinculada ao contrato
6. Ver lancamento financeiro vinculado a proposta/contrato

### Testar Multi-Tenancy
1. Login como `admin@geoprime-topografia.demo` -> ver 40 leads
2. Logout -> login como `admin@campo-forte-consultoria.demo` -> ver 19 leads
3. Confirmar que nenhum dado do GeoPrime aparece no Campo Forte

---

## Comandos Uteis

```bash
# Popular dados demo
python manage.py seed_demo_data

# Resetar e re-popular
python manage.py reset_demo_data

# Apenas limpar (sem re-popular)
python manage.py reset_demo_data --no-reseed

# Rodar o servidor
python manage.py runserver
```

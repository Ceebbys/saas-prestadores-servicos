# Cenarios Demo

## Visao Geral

O seed demo cria **5 empresas** de segmentos diferentes com dados completos e coerentes
para testar todas as funcionalidades do sistema.

### Resumo Quantitativo

| Empresa | Segmento | Leads | Propostas | Contratos | OS | Financeiro |
|---------|----------|:-----:|:---------:|:---------:|:--:|:----------:|
| GeoPrime Topografia | Topografia | 40 | 20 | 15 | 25 | 40 |
| Studio Alto Arquitetura | Arquitetura | 28 | 14 | 9 | 16 | 28 |
| Alfa Assistencia Tecnica | Manutencao | 28 | 14 | 9 | 16 | 28 |
| Campo Forte Consultoria | Consultoria | 15 | 8 | 5 | 8 | 15 |
| Luz & Instalacoes | Outro (Eletrica) | 28 | 14 | 9 | 16 | 28 |
| **Total** | | **139** | **70** | **47** | **81** | **139** |

- **20 usuarios** (4 por empresa)
- **~120 oportunidades** no pipeline
- **~210 itens de proposta**
- **~480 itens de checklist** nas OS

---

## Pipelines por Empresa

### GeoPrime Topografia
```
Primeiro Contato -> Levantamento de Campo -> Processamento -> Entrega Tecnica -> Fechado/Ganho | Fechado/Perdido
```

### Studio Alto Arquitetura
```
Contato Inicial -> Briefing -> Estudo Preliminar -> Anteprojeto -> Projeto Executivo -> Fechado/Ganho | Fechado/Perdido
```

### Alfa Assistencia Tecnica
```
Solicitacao -> Visita Tecnica -> Orcamento -> Reparo -> Finalizacao -> Fechado/Ganho | Fechado/Perdido
```

### Campo Forte Consultoria
```
Prospeccao -> Diagnostico -> Proposta -> Plano de Acao -> Entrega -> Fechado/Ganho | Fechado/Perdido
```

### Luz & Instalacoes
```
Contato -> Vistoria -> Orcamento -> Instalacao -> Testes -> Entrega -> Fechado/Ganho | Fechado/Perdido
```

---

## Tipos de Servico por Empresa

### GeoPrime
- Levantamento Planialtimetrico (24h)
- Georreferenciamento de Imovel (16h)
- Locacao de Obra (8h)
- Mapeamento Aereo com Drone (12h)
- Cadastro de Redes (16h)

### Studio Alto
- Projeto Residencial (120h)
- Projeto Comercial (160h)
- Design de Interiores (80h)
- Reforma e Retrofit (60h)
- Regularizacao de Imovel (40h)

### Alfa
- Manutencao Preventiva (4h)
- Manutencao Corretiva (6h)
- Instalacao de Equipamento (8h)
- Visita Tecnica (2h)
- Troca de Pecas (3h)

### Campo Forte
- Diagnostico Organizacional (40h)
- Consultoria Estrategica (80h)
- Treinamento In Company (16h)
- Auditoria de Processos (24h)

### Luz & Instalacoes
- Instalacao Eletrica Residencial (16h)
- Instalacao Eletrica Comercial (40h)
- Quadro de Distribuicao (8h)
- Instalacao de Luminarias (6h)
- Laudo Eletrico NR-10 (12h)
- Manutencao Eletrica (4h)

---

## Cenarios Interessantes para Teste

### 1. Dashboard com metricas reais
**Empresa:** GeoPrime Topografia (admin)
- Leads novos no mes corrente
- Propostas abertas e aceitas com valores
- OS pendentes e em andamento
- Receitas e despesas do mes
- Inadimplencia (entries vencidas)
- Pipeline resumido com valores por etapa

### 2. Pipeline Kanban cheio
**Empresa:** GeoPrime Topografia (admin)
- Oportunidades distribuidas em todas as colunas
- Valores e probabilidades variados
- Oportunidades ganhas e perdidas

### 3. Listas paginadas
**Empresa:** GeoPrime Topografia
- 40 leads (pagina 1 = 20, pagina 2 = 20)
- Testar filtros por status, origem, busca por nome

### 4. Empresa minimalista
**Empresa:** Campo Forte Consultoria
- 15 leads (sem paginacao)
- Poucos registros em cada modulo
- Ideal para testar empty states e layout com poucos dados

### 5. Fluxo completo Lead -> Receita
**Empresa:** Qualquer (GeoPrime recomendada)
- Leads convertidos tem oportunidades ganhas
- Propostas aceitas tem contratos vinculados
- Contratos ativos tem OS vinculadas
- Lancamentos financeiros vinculados a propostas/contratos/OS

### 6. OS com checklists parciais
**Empresa:** Qualquer
- OS em andamento: checklist parcialmente preenchido
- OS concluida: checklist 100% preenchido
- OS pendente: checklist vazio

### 7. Financeiro com inadimplencia
**Empresa:** Qualquer
- Entries com status OVERDUE (vencimento no passado)
- Entries PENDING com vencimento proximo
- Mix de receitas e despesas pagas
- Dashboard mostra contagem de inadimplentes

### 8. Filtros e buscas
**Empresa:** GeoPrime ou Studio Alto
- Filtrar leads por status (novo, contatado, qualificado, perdido, convertido)
- Filtrar leads por origem (site, indicacao, google, instagram, telefone)
- Filtrar propostas por status
- Filtrar contratos por status
- Filtrar OS por status, prioridade, responsavel
- Filtrar financeiro por tipo, status, categoria, periodo

### 9. Pipeline com etapas longas
**Empresa:** Luz & Instalacoes
- 8 etapas no pipeline (o mais longo)
- Testar scroll horizontal ou responsividade do board

### 10. Multiplos usuarios por empresa
**Empresa:** Qualquer
- Login como admin: ve tudo
- Login como comercial: ve tudo (gerente)
- Login como tecnico: ve tudo (membro)
- Login como financeiro: ve tudo (membro)
- Todos compartilham o mesmo contexto da empresa

---

## Distribuicao de Status nos Dados

### Leads
- ~25% Novo (recentes, ultimos 30 dias)
- ~20% Contatado
- ~25% Qualificado (geram oportunidades e propostas)
- ~15% Convertido (geram oportunidades ganhas)
- ~15% Perdido

### Propostas
- ~20% Rascunho
- ~15% Enviada
- ~10% Visualizada
- ~30% Aceita (maioria gera contratos)
- ~15% Rejeitada
- ~10% Expirada

### Contratos
- ~15% Rascunho
- ~10% Enviado
- ~15% Assinado
- ~30% Ativo (com datas de inicio/fim)
- ~20% Concluido
- ~10% Cancelado

### Ordens de Servico
- ~15% Pendente
- ~20% Agendada (algumas atrasadas)
- ~25% Em Andamento
- ~5% Pausada
- ~30% Concluida
- ~5% Cancelada

### Financeiro
- ~40% Pago
- ~30% Pendente
- ~20% Vencido (inadimplente)
- ~10% Cancelado

---

## Dados Temporais

- Dados distribuidos nos ultimos **6 meses**
- Peso maior para dados recentes (35% ultimo mes)
- Garantia de dados no mes corrente para dashboard funcional
- OS agendadas no futuro para calendario
- OS atrasadas (agendada no passado, ainda SCHEDULED)
- Financeiro com vencimentos passados para inadimplencia

# Acessos Demo

> Todos os acessos usam a senha **`Demo123!`**
>
> Os emails seguem o padrao `{role}@{slug-da-empresa}.demo`
>
> Para ver os emails exatos, rode: `python manage.py seed_demo_data`

## 1. GeoPrime Topografia

| Nome | Email | Papel |
|------|-------|-------|
| Ricardo Mendes | `admin@geoprime-topografia.demo` | Proprietario (Owner) |
| Camila Torres | `comercial@geoprime-topografia.demo` | Gerente (Manager) |
| Bruno Almeida | `tecnico@geoprime-topografia.demo` | Membro (Tecnico) |
| Fernanda Costa | `financeiro@geoprime-topografia.demo` | Membro (Financeiro) |

**Segmento:** Topografia
**Volume:** Pesado (40 leads, 20 propostas, 15 contratos, 25 OS, 40 financeiros)
**O que testar:** Pipeline cheio, listas paginadas, dashboard com metricas ricas, variedade de status

---

## 2. Studio Alto Arquitetura

| Nome | Email | Papel |
|------|-------|-------|
| Mariana Lopes | `admin@studio-alto-arquitetura.demo` | Proprietario (Owner) |
| Gabriel Oliveira | `comercial@studio-alto-arquitetura.demo` | Gerente (Manager) |
| Juliana Ferreira | `tecnico@studio-alto-arquitetura.demo` | Membro (Tecnico) |
| Paulo Ribeiro | `financeiro@studio-alto-arquitetura.demo` | Membro (Financeiro) |

**Segmento:** Arquitetura
**Volume:** Padrao (28 leads, 14 propostas, 9 contratos, 16 OS, 28 financeiros)
**O que testar:** Pipeline com 7 etapas, propostas com itens por m2, fluxo completo lead-proposta-contrato

---

## 3. Alfa Assistencia Tecnica

| Nome | Email | Papel |
|------|-------|-------|
| Antonio Vieira | `admin@alfa-assistencia-tecnica.demo` | Proprietario (Owner) |
| Luciana Cardoso | `comercial@alfa-assistencia-tecnica.demo` | Gerente (Manager) |
| Marcio Nunes | `tecnico@alfa-assistencia-tecnica.demo` | Membro (Tecnico) |
| Debora Freitas | `financeiro@alfa-assistencia-tecnica.demo` | Membro (Financeiro) |

**Segmento:** Manutencao
**Volume:** Padrao (25 leads, 12 propostas, 8 contratos, 15 OS, 25 financeiros)
**O que testar:** OS com checklists de visita tecnica, propostas de baixo valor unitario, contratos de manutencao

---

## 4. Campo Forte Consultoria

| Nome | Email | Papel |
|------|-------|-------|
| Helena Martins | `admin@campo-forte-consultoria.demo` | Proprietario (Owner) |
| Renato Barbosa | `comercial@campo-forte-consultoria.demo` | Gerente (Manager) |
| Cintia Araujo | `tecnico@campo-forte-consultoria.demo` | Membro (Tecnico) |
| Fabio Teixeira | `financeiro@campo-forte-consultoria.demo` | Membro (Financeiro) |

**Segmento:** Consultoria
**Volume:** Minimo (15 leads, 8 propostas, 5 contratos, 8 OS, 15 financeiros)
**O que testar:** Empresa com pouco volume, listas sem paginacao, empty states em alguns contextos

---

## 5. Luz & Instalacoes

| Nome | Email | Papel |
|------|-------|-------|
| Sergio Rocha | `admin@luz-instalacoes.demo` | Proprietario (Owner) |
| Viviane Dias | `comercial@luz-instalacoes.demo` | Gerente (Manager) |
| Anderson Moreira | `tecnico@luz-instalacoes.demo` | Membro (Tecnico) |
| Patricia Gomes | `financeiro@luz-instalacoes.demo` | Membro (Financeiro) |

**Segmento:** Instalacao tecnica (Outro)
**Volume:** Padrao (28 leads, 14 propostas, 9 contratos, 16 OS, 28 financeiros)
**O que testar:** Pipeline com 8 etapas (mais longo), propostas com itens por ponto, servicos eletricos

---

## Comandos

```bash
# Popular dados demo
python manage.py seed_demo_data

# Resetar e re-popular
python manage.py reset_demo_data

# Apenas limpar (sem re-popular)
python manage.py reset_demo_data --no-reseed
```

## Nota sobre slugs

Os emails usam o slug da empresa (gerado automaticamente a partir do nome).
Se o banco ja tiver uma empresa com slug conflitante, o Django adiciona um sufixo numerico
(ex: `geoprime-topografia-1`). O comando exibe os emails exatos ao final da execucao.

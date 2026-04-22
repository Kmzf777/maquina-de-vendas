# Estatisticas - Sistema de Custo de Tokens IA

**Data:** 2026-03-30
**Status:** Aprovado

## Objetivo

Criar uma pagina de Estatisticas no CRM com tracking completo de custos de tokens do agente IA. O sistema captura o uso de tokens em cada chamada a OpenAI, armazena com o preco vigente, e exibe dashboards com filtros por periodo, stage, modelo e lead.

## Decisoes de Design

- Tracking apenas de dados futuros (nao retroativo)
- Custos exibidos em USD
- Precos configurados no sistema e gravados junto com cada registro (historico de precos preservado)
- Granularidade: por lead, por stage, por modelo, e visao geral
- Abordagem: tabela dedicada `token_usage` (1 registro por chamada API)

---

## 1. Modelo de Dados

### Tabela `token_usage`

| Coluna | Tipo | Descricao |
|--------|------|-----------|
| `id` | uuid (PK, default gen_random_uuid()) | Identificador unico |
| `lead_id` | uuid (FK -> leads) | Lead que gerou o custo |
| `stage` | text NOT NULL | Stage do agente no momento (secretaria, atacado, etc.) |
| `model` | text NOT NULL | Modelo usado (gpt-4.1, gpt-4.1-mini) |
| `call_type` | text NOT NULL | Tipo: `classification`, `media_transcription`, `media_description`, `response` |
| `prompt_tokens` | integer NOT NULL DEFAULT 0 | Tokens de entrada |
| `completion_tokens` | integer NOT NULL DEFAULT 0 | Tokens de saida |
| `price_per_input_token` | numeric NOT NULL | Preco por token de entrada (USD) no momento da chamada |
| `price_per_output_token` | numeric NOT NULL | Preco por token de saida (USD) no momento da chamada |
| `total_cost` | numeric NOT NULL | Custo total calculado (USD) |
| `created_at` | timestamptz DEFAULT now() | Momento da chamada |

Indices:
- `idx_token_usage_lead_id` em `lead_id`
- `idx_token_usage_created_at` em `created_at`
- `idx_token_usage_stage` em `stage`
- `idx_token_usage_model` em `model`

Habilitar real-time: `ALTER PUBLICATION supabase_realtime ADD TABLE token_usage;`

### Tabela `model_pricing`

| Coluna | Tipo | Descricao |
|--------|------|-----------|
| `id` | uuid (PK, default gen_random_uuid()) | Identificador unico |
| `model` | text UNIQUE NOT NULL | Nome do modelo |
| `price_per_input_token` | numeric NOT NULL | Preco atual por token de entrada (USD) |
| `price_per_output_token` | numeric NOT NULL | Preco atual por token de saida (USD) |
| `updated_at` | timestamptz DEFAULT now() | Ultima atualizacao |

Seed com precos atuais:

| Modelo | Input (por 1M tokens) | Output (por 1M tokens) |
|--------|----------------------|------------------------|
| gpt-4.1 | $2.00 | $8.00 |
| gpt-4.1-mini | $0.40 | $1.60 |

---

## 2. Backend (FastAPI)

### Modulo `app/agent/token_tracker.py`

Funcao principal:

```python
async def track_usage(lead_id: str, stage: str, model: str, call_type: str, usage, supabase):
    # 1. Busca preco atual do modelo em model_pricing
    # 2. Calcula total_cost = (prompt_tokens * price_input) + (completion_tokens * price_output)
    # 3. INSERT na tabela token_usage
```

### Pontos de captura no orchestrator.py

4 pontos onde `response.usage` e capturado:

1. **Classificacao** (`call_type: classification`) - chamada que classifica o stage do lead
2. **Transcricao de audio** (`call_type: media_transcription`) - via Whisper (sem tokens, custo fixo por minuto)
3. **Descricao de imagem** (`call_type: media_description`) - GPT-4 analisa a imagem
4. **Resposta principal** (`call_type: response`) - resposta do agente ao lead

Nota sobre Whisper: nao retorna tokens, cobra $0.006/min. Gravar com `prompt_tokens: 0`, `completion_tokens: 0` e `total_cost` estimado.

### API Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/api/stats/costs` | Custos agregados com filtros (periodo, stage, modelo, lead) |
| GET | `/api/stats/costs/daily` | Custos agrupados por dia (grafico de linha) |
| GET | `/api/stats/costs/breakdown` | Custos agrupados por stage/modelo/lead (graficos de barra) |
| GET | `/api/model-pricing` | Listar precos configurados |
| PUT | `/api/model-pricing/{model}` | Atualizar preco de um modelo |

### Parametros de filtro (query params)

- `start_date` (ISO date) - inicio do periodo
- `end_date` (ISO date) - fim do periodo
- `stage` (text, opcional) - filtrar por stage
- `model` (text, opcional) - filtrar por modelo
- `lead_id` (uuid, opcional) - filtrar por lead

---

## 3. Frontend - Pagina de Estatisticas

### Sidebar

Novo item no `NAV_ITEMS` em `sidebar.tsx`:
- Label: "Estatisticas"
- Rota: `/estatisticas`
- Posicao: antes de "Configuracoes"
- Icone: grafico/chart icon

### Rota

Nova pagina em: `crm/src/app/(authenticated)/estatisticas/page.tsx`

### Layout da pagina

**Topo:**
- Titulo "Estatisticas"
- Filtro de periodo: botoes rapidos (Hoje, 7 dias, 30 dias) + date picker customizado
- Seletor de mes (para visao mensal)

**Cards de resumo (4 cards):**
- Custo Total - valor em USD no periodo
- Total de Chamadas - numero de chamadas a API
- Tokens Consumidos - prompt + completion totais
- Custo Medio por Lead - custo total / leads unicos

**Grafico de linha:**
- Evolucao do custo diario ao longo do periodo selecionado
- Eixo X: dias, Eixo Y: custo USD

**Graficos de barra (lado a lado):**
- Por Stage - custo de cada stage (secretaria, atacado, etc.)
- Por Modelo - custo gpt-4.1 vs gpt-4.1-mini

**Tabela detalhada:**
- Top leads por custo
- Colunas: Lead (nome/telefone), Stage, Chamadas, Tokens, Custo Total
- Ordenavel e com paginacao

### Biblioteca de graficos

Recharts - leve, compativel com React/Next.js.

---

## 4. Configuracao de Precos

Na pagina `/config` existente, nova secao **"Precos de Modelos IA"**:

- Lista dos modelos cadastrados na tabela `model_pricing`
- Para cada modelo: campos editaveis de preco por input token e output token
- Botao salvar (PUT `/api/model-pricing/{model}`)
- Exibe data da ultima atualizacao

---

## 5. Escopo Tecnico Resumido

### Arquivos novos:
- `backend-evolution/migrations/XXX_add_token_usage.sql` - migration
- `backend-evolution/app/agent/token_tracker.py` - modulo de tracking
- `backend-evolution/app/stats/router.py` - endpoints de estatisticas
- `crm/src/app/(authenticated)/estatisticas/page.tsx` - pagina de estatisticas

### Arquivos modificados:
- `backend-evolution/app/agent/orchestrator.py` - captura de usage em cada chamada
- `backend-evolution/app/main.py` - registrar router de stats
- `crm/src/components/sidebar.tsx` - adicionar item Estatisticas
- `crm/src/app/(authenticated)/config/page.tsx` - secao de precos de modelos

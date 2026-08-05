# Spec — /trafego: ROAS (Google Ads) + filtro de data avançado

**Data:** 2026-08-05
**Status:** decisões travadas; pendente review do spec

## Objetivo

1. **F1 — Filtro de data avançado:** além dos presets (7/30/90d, tudo), permitir escolher
   **por mês** e por **período custom** (de/até).
2. **F2 — ROAS por campanha:** conectar a **API do Google Ads** para trazer o **investimento
   (spend) por campanha** e exibir **Investimento** e **ROAS** (receita ÷ investimento) no
   Relatório Campanhas. Só Google agora; Meta depois (mesma arquitetura, `platform` na tabela).

F1 é **pré-requisito** de F2 (o spend precisa casar com a janela escolhida) e ship primeiro.

## Decisões travadas (brainstorming)
- **Chave de junção:** `utm_campaign` (do lead) == **nome da campanha** do Google Ads
  (`campaign.name`), normalizado (trim + lower).
- **Freshness:** **sync diário** do spend para a tabela `ad_spend`; o relatório lê de lá.
- **Credenciais:** **env/secrets** `GOOGLE_ADS_*` (padrão dos `GMAIL_*` já existentes). Sem UI.

## Pré-requisito externo (F2)
Acesso à API do Google Ads: **developer token aprovado** + OAuth (client id/secret, refresh
token), `login_customer_id` e `customer_id` da conta. Sem isso, o código fica **env-gated e
fail-soft** (não quebra nada; ROAS mostra "—" até as credenciais + sync existirem).

---

## F1 — Filtro de data avançado

### Backend
- Os endpoints `/api/traffic/report` e `/api/traffic/leads` passam a aceitar, além de
  `period`, os parâmetros opcionais **`date_from`** e **`date_to`** (YYYY-MM-DD). Quando
  presentes, definem a janela explicitamente (têm precedência sobre `period`).
- `_period_cutoff(period)` continua para os presets; adicionar suporte a **limite superior**:
  hoje só há cutoff inferior. Introduzir `_resolve_window(period, date_from, date_to) ->
  (cutoff_lo, cutoff_hi)` (ISO ou None). `_fetch_leads`/`_sales_by_lead` filtram
  `created_at`/`sold_at` por `>= lo` **e** `<= hi` (quando hi definido).
- "Mês" é conveniência do front (converte para `date_from`/`date_to` do 1º ao último dia do
  mês) — o backend só entende janela genérica.

### Frontend (`page.tsx` + control novo)
- Substituir o `Select` de período por um controle com: **presets** (7/30/90d, Tudo),
  **seletor de mês** e **intervalo custom** (de/até). Usar shadcn/ui + inputs nativos
  (`<input type="month">` / `type="date">`) estilizados à paleta, para não adicionar
  dependência de calendário. O modo escolhido monta `period` OU `date_from`/`date_to` na URL
  dos fetches.
- Aplicar a skill `frontend-design` (consistência/minimalismo; reusar tokens).

---

## F2 — ROAS via Google Ads API

### Componentes
1. **Config** (`app/config.py`): ler `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`,
   `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID`,
   `GOOGLE_ADS_CUSTOMER_ID`. `google_ads_enabled` = todas presentes.
2. **Client** (`app/campaigns/google_ads.py`, módulo novo): usa a lib `google-ads`
   (adicionar a `requirements.txt`). Função
   `fetch_campaign_spend(date_from, date_to) -> list[{campaign_id, campaign_name, date, cost}]`
   via GAQL:
   ```
   SELECT campaign.id, campaign.name, segments.date, metrics.cost_micros
   FROM campaign WHERE segments.date BETWEEN '{from}' AND '{to}'
   ```
   `cost = cost_micros / 1_000_000`. **Env-gated** (creds ausentes → `[]`) e **fail-soft**
   (erro de API → `[]`, log). Toda a lógica de parsing é uma função pura testável separada da
   chamada de rede.
3. **Tabela `ad_spend`** (migration nova):
   ```sql
   CREATE TABLE IF NOT EXISTS ad_spend (
     id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
     platform text NOT NULL DEFAULT 'google',
     campaign_id text,
     campaign_name text NOT NULL,
     date date NOT NULL,
     cost numeric NOT NULL DEFAULT 0,
     currency text NOT NULL DEFAULT 'BRL',
     updated_at timestamptz NOT NULL DEFAULT now(),
     UNIQUE (platform, campaign_id, date)
   );
   CREATE INDEX IF NOT EXISTS ad_spend_platform_name_date_idx
     ON ad_spend (platform, campaign_name, date);
   ```
4. **Sync** (`app/campaigns/ad_spend_sync.py` + script `scripts/sync_google_ads_spend.py`):
   `sync_google_ads_spend(days=30)` chama `fetch_campaign_spend` para a janela e faz **upsert**
   em `ad_spend` (on conflict platform+campaign_id+date → cost/updated_at). Idempotente. O
   script é rodado por **cron diário** na VPS (ops — fora do código). Env-gated: no-op se
   `google_ads_enabled` for False.
5. **Leitura no relatório** (`traffic_report.py`):
   - Novo `_spend_by_campaign(sb, cutoff_lo, cutoff_hi, platform="google") -> dict[str, float]`:
     soma `cost` por `campaign_name` normalizado (trim+lower) dentro da janela.
   - `build_campaign_report` recebe `spend_by_campaign` e, **apenas para linhas de canal
     "Google Ads"**, define `investimento = spend_by_campaign.get(norm(campaign), 0.0)` e
     `roas = receita / investimento` (0.0/None se investimento == 0). Outros canais:
     `investimento = None`, `roas = None`.
   - **Total:** `investimento` total = soma dos investimentos das linhas Google;
     **ROAS total** = (soma da receita das linhas **Google**) ÷ (investimento total) — não
     mistura receita de outros canais no denominador/numerador do ROAS.
6. **Frontend** (`campaign-report-table.tsx`): colunas **Investimento** (R$) e **ROAS**
   (ex.: `3.2x`, "—" quando sem spend/None). Só populadas para canal "Google Ads".

### Fluxo de dados (F2)
`cron diário → sync_google_ads_spend → Google Ads API → upsert ad_spend`
`/trafego → traffic_report lê ad_spend (janela) → junta por campaign_name → ROAS por linha`

## Tratamento de erros
- `google_ads.py` e o sync: env-gated + fail-soft (nunca levantam; log + no-op).
- Report: se não há spend na janela (sync não rodou / sem creds) → investimento 0/None,
  ROAS "—". Nunca quebra o relatório (mantém o fail-soft atual).
- Migration idempotente (`IF NOT EXISTS`).

## Testes
- F1: `_resolve_window` (preset, mês, custom, precedência de date_from/to; upper bound aplicado
  em `_fetch_leads`/`_sales_by_lead`). Frontend: type-check/lint/tests verdes; controle monta a
  URL certa.
- F2: parsing puro de `fetch_campaign_spend` (mock da resposta → cost_micros→cost); env-gate
  (sem creds → []); `_spend_by_campaign` agrega e normaliza nome; `build_campaign_report` com
  spend → investimento/roas nas linhas Google, None nas demais, e ROAS total só sobre Google;
  upsert do sync idempotente (supabase mock). Nunca chamar a API real nos testes.

## Escopo / faseamento
- **Fase 1 (F1):** filtro de data — plano e execução primeiro (sem deps externas).
- **Fase 2 (F2):** ROAS Google Ads — plano e execução depois; ativa em prod quando os secrets
  `GOOGLE_ADS_*` + o cron de sync existirem.
- **Fora de escopo:** Meta Ads (só a coluna `platform` já preparada), otimização de campanha,
  automações sobre ROAS.

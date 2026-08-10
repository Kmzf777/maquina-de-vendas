# Spec — Conectar Meta Ads (investimento/ROAS no /trafego)

**Data:** 2026-08-10
**Status:** pré-aprovado; execução via subagents

## Objetivo
Trazer o **investimento (spend) por campanha do Meta Ads** para a tabela `ad_spend`
(`platform='meta'`) e exibir **Investimento** e **ROAS** também nas linhas de canal **Meta Ads**
do Relatório Campanhas — espelhando o que já existe para o Google.

## Contexto (o que já está pronto)
- `ad_spend` já tem coluna `platform` (migration 20260805). Sem migration nova.
- `_spend_by_campaign(sb, lo, hi, platform=...)` já é parametrizado por plataforma.
- Casamento utm_campaign ↔ nome da campanha: exact (trim+lower) + **fuzzy por tokens**
  (`_fuzzy_spend_lookup`, ignora números e `sitelink`) — reutilizado para o Meta.
- O worker já roda o sync diário e há o botão "Atualizar"; o CAPI Meta já usa httpx.

## Decisões travadas
- **Credenciais dedicadas:** `META_ADS_ACCESS_TOKEN` (System User com `ads_read`) +
  `META_AD_ACCOUNT_ID`. Fallback: se `META_ADS_ACCESS_TOKEN` ausente, tenta `META_ACCESS_TOKEN`.
- Versão da Graph API: `META_API_VERSION` (env já existente) com default `v21.0`.

## Componentes

### 1. Cliente Meta Marketing API (`backend/app/campaigns/meta_ads.py`, novo)
- `meta_ads_enabled()` = token (`META_ADS_ACCESS_TOKEN` ou `META_ACCESS_TOKEN`) **e** `META_AD_ACCOUNT_ID` presentes.
- `parse_spend_rows(data)` — puro: de `insights.data` → `[{campaign_id, campaign_name, date, cost}]`
  (`date` = `date_start`; `cost` = `float(spend)`); ignora linhas sem `campaign_name`/`spend`.
- `async fetch_campaign_spend(date_from, date_to)` — httpx REST, **env-gated** ([] sem creds) e
  **fail-soft** ([] em erro). Chama:
  `GET https://graph.facebook.com/{version}/act_{ad_account_id}/insights`
  params: `level=campaign`, `fields=campaign_id,campaign_name,spend`,
  `time_range={"since":from,"until":to}`, `time_increment=1`, `limit=500`, `access_token=…`.
  Pagina via `paging.next`. Normaliza o ad account id (garante prefixo `act_`).

### 2. Sync (`backend/app/campaigns/ad_spend_sync.py`, estender)
- Adicionar `async sync_meta_ads_spend(days=30) -> int` (espelha o do Google; upsert `platform='meta'`).
- Adicionar `async sync_all_ad_spend(days=30) -> dict` = roda Google + Meta (cada um env-gated/fail-soft)
  → `{"google": <int>, "meta": <int>}`.
- `_ad_spend_sync_tick` (worker) passa a chamar `sync_all_ad_spend`.

### 3. Endpoint manual (`backend/app/campaigns/traffic_router.py`)
- Renomear `POST /api/traffic/sync-google-ads` → `POST /api/traffic/sync-ads`, chamando
  `sync_all_ad_spend` e retornando `{"google": g, "meta": m, "synced": g+m}` (mantém `synced`
  total p/ o toast do botão). Atualizar o proxy Next para apontar ao novo caminho.

### 4. Report — ROAS por canal pago (`backend/app/campaigns/traffic_report.py`)
- Generalizar de "só Google" para um **mapa por canal**. `build_campaign_report` troca o param
  `spend_by_campaign: dict[str,float]` por `spend_by_channel: dict[str, dict[str, float]]`
  (canal → {campaign_name_norm: cost}).
  - Atribuição: para cada `row`, se `row["channel"]` está em `spend_by_channel`, calcula
    `investimento` (exact + fuzzy) daquele mapa; `roas = receita/investimento`.
  - Total ROAS: `paid_receita` = soma da receita das linhas cujo canal é pago (∈ `spend_by_channel`)
    ÷ investimento total. (Antes era só `google_receita`.)
- `traffic_report` e `campaign_detail` montam:
  `spend_by_channel = {"Google Ads": _spend_by_campaign(sb,lo,hi,"google"), "Meta Ads": _spend_by_campaign(sb,lo,hi,"meta")}`.

### 5. Frontend (mostrar Investimento/ROAS p/ Meta também)
- `campaign-report-table.tsx`: a célula de Investimento hoje mostra só se `channel === "Google Ads"`.
  Trocar para mostrar quando **há investimento** (`r.investimento > 0`), cobrindo Google **e** Meta.
  ROAS já usa `fmtRoas(r.roas)` ("—" quando null) — ok.
- `campaign-kpis.tsx` (página de detalhe): os cards Investimento/ROAS hoje aparecem só p/
  `channel === "Google Ads"`; passar a mostrar quando `summary.investimento > 0` ou o canal for pago.

### 6. Config + Tutorial
- Ler `META_ADS_ACCESS_TOKEN`/`META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, `META_API_VERSION` via `os.getenv`.
- Novo doc `docs/setup/meta-ads-conexao.md`: Business Manager → System User → conceder
  **ads_read** na conta de anúncios → gerar token → pegar o **Ad Account ID** (act_…) → setar
  os 2 secrets. Mesmo padrão do `google-ads-conexao.md`.

## Tratamento de erros
- `meta_ads.py` e o sync: env-gated + fail-soft (nunca levantam; [] / 0).
- `_spend_by_campaign(platform="meta")` já é fail-soft.
- Report mantém o fail-soft atual.

## Testes
- `meta_ads.py`: `parse_spend_rows` puro (spend→cost, ignora malformado); `meta_ads_enabled`
  (token+account); `fetch_campaign_spend` no-op sem creds (nunca chama a API real nos testes).
- `sync_meta_ads_spend` / `sync_all_ad_spend`: env-gate no-op; upsert `platform='meta'`; retorno agregado.
- `build_campaign_report` com `spend_by_channel`: investimento/ROAS nas linhas Google **e** Meta;
  canais não-pagos sem investimento; total ROAS = receita paga ÷ investimento. (Atualizar os
  testes existentes que passavam `spend_by_campaign` p/ o novo `spend_by_channel`.)
- Frontend: type-check/eslint/tests verdes; Investimento/ROAS renderiza p/ Meta.

## Ativação (usuário)
- Setar `META_ADS_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` no `.env` da VPS (api + worker).
- Nada de migration. Após deploy, o worker sincroniza Meta no boot; o botão "Atualizar" força.
- Casamento por campanha: alinhar `utm_campaign` ao **nome da campanha no Meta** (o fuzzy ajuda,
  mas nomes muito diferentes não casam — documentar no tutorial).

## Fora de escopo
- Currency conversion (assume conta em BRL; `cost` = valor na moeda da conta, `currency='BRL'`).
- TikTok/Bing; breakdown por ad/adset (só nível campanha).

## Decisões finais
1. Cliente Meta Marketing API via httpx (espelha `google_ads.py`), env-gated/fail-soft.
2. Sync unificado (`sync_all_ad_spend`) no worker + botão; endpoint `/api/traffic/sync-ads`.
3. Report generaliza ROAS para canais pagos via `spend_by_channel`.
4. Frontend mostra Investimento/ROAS quando há investimento (Google **e** Meta).
5. Credenciais dedicadas `META_ADS_ACCESS_TOKEN` + `META_AD_ACCOUNT_ID` (+ tutorial).

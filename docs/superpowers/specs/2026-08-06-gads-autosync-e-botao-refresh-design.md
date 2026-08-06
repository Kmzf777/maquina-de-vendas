# Spec — Auto-sync diário do Google Ads (no worker) + botão de refresh no /trafego

**Data:** 2026-08-06
**Status:** pré-aprovado; execução via subagents

## Problema
O ROAS não aparece porque a tabela `ad_spend` está **vazia**: o único preenchedor é o script
`scripts/sync_google_ads_spend.py`, e **nada o executa** (sem cron, e reiniciar a app não roda).
O usuário nunca configurou cron e não quer ops manual.

## Objetivo
1. **Auto-sync no backend** (in-app, sem cron de SO nem Supabase): o worker roda o sync do
   Google Ads sozinho, ~1×/dia (e no startup) — usando o container que já tem as credenciais.
2. **Botão de refresh** no `/trafego`: dispara o sync sob demanda e recarrega os dados, para o
   admin não esperar o tick diário.

> **Por que não Supabase cron:** `pg_cron` roda SQL dentro do Postgres, que não faz o
> OAuth/HTTP do Google Ads de forma limpa. O backend (Python, httpx, já com as creds) é o
> lugar certo. O agendamento vira **código** (tick no worker), não infra externa.

## Peça 1 — Auto-sync no worker
- O worker (`app/campaign/worker.py` → `app/worker/main.py::run_worker`) registra loops em
  `TASK_SPECS` via `run_periodic(name, fn, interval)` (roda `fn` no startup e a cada `interval`).
- Adicionar:
  ```python
  async def _ad_spend_sync_tick() -> None:
      from app.campaigns.ad_spend_sync import sync_google_ads_spend
      await sync_google_ads_spend(days=30)
  ```
  e a entrada `("ad-spend-sync", "periodic", _ad_spend_sync_tick, 86400)` em `TASK_SPECS`.
- Comportamento: roda **no próximo restart do worker** (destrava agora) e **a cada 24h**.
  `sync_google_ads_spend` já é **env-gated** (no-op sem as 6 `GOOGLE_ADS_*`) e **fail-soft**
  (o `run_periodic` também isola exceções do tick). Upsert idempotente → repetir é seguro.
- O worker já recebe as env vars (`docker-compose.yml`: `worker` tem `env_file: .env`, igual à api).

## Peça 2 — Endpoint de sync manual + botão
- **Backend** `traffic_router.py`: `POST /api/traffic/sync-google-ads` → `await
  sync_google_ads_spend(days=30)` → `{"synced": <int>}`. (Endpoint FastAPI async; a proteção
  admin fica na proxy do Next.)
- **Proxy Next** `frontend/src/app/api/traffic/sync/route.ts` (POST, admin-gated, igual aos
  outros; 401/403/502) → encaminha para `${backend}/api/traffic/sync-google-ads`.
- **Frontend** `/trafego/page.tsx`: botão **"Atualizar"** no header (ao lado dos filtros). Ao
  clicar: `POST` no proxy → estado de loading no botão (spinner/disabled) → ao concluir, refaz
  o fetch do report (`fetchReport`) → toast curto com o resultado
  (`N linhas sincronizadas` ou `Sem dados do Google Ads`). Se o POST falhar, refaz o fetch
  mesmo assim (o botão também serve de "recarregar"). frontend-design + shadcn.

## Componentes / arquivos
- Modify `backend/app/worker/main.py` — `_ad_spend_sync_tick` + entrada em `TASK_SPECS`.
- Modify `backend/app/campaigns/traffic_router.py` — endpoint `POST /api/traffic/sync-google-ads`.
- Modify `backend/tests/test_traffic_report.py` (ou novo test) — cobre TASK_SPECS + endpoint.
- Create `frontend/src/app/api/traffic/sync/route.ts` — proxy admin-gated.
- Modify `frontend/src/app/(authenticated)/trafego/page.tsx` — botão Atualizar + handler.

## Tratamento de erros
- Tick e endpoint: `sync_google_ads_spend` já é fail-soft (retorna 0, loga). Nunca derruba o worker/request.
- Botão: erro no POST → toast de erro + ainda refaz o fetch do report.

## Testes
- Backend: `TASK_SPECS` inclui `("ad-spend-sync", "periodic", …)` com callable async; o endpoint
  `/api/traffic/sync-google-ads` existe e chama `sync_google_ads_spend` (monkeypatch → não bate na API real).
- Frontend: type-check/eslint/tests verdes; proxy admin-gate em `/api/traffic/sync` (o teste
  proxy-coverage já cobre `/api/traffic` no matcher). Smoke do botão (loading/estado).

## Ativação (sem ação nova do usuário além do que já fez)
- As `GOOGLE_ADS_*` já estão no `.env` da VPS (api + worker). Após o deploy desta mudança, o
  worker roda o sync **no boot** → `ad_spend` popula → ROAS aparece. O botão permite forçar na hora.
- Continua valendo: developer token precisa de **Basic access** (senão a API volta 0), e
  `utm_campaign` deve casar com o nome da campanha no Google Ads.

## Fora de escopo
- Cron de SO / GitHub Actions agendado (substituídos pelo tick no worker).
- Guarda de "freshness" no tick (YAGNI; upsert idempotente, custo de API por query diária é baixo).
- Meta Ads.

## Decisões
1. Agendamento = **tick no worker** (`run_periodic`, 24h), não cron externo nem Supabase.
2. Botão "Atualizar" dispara o sync + recarrega o report.

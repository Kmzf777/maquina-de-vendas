# Painel visual do motor de Follow-up (aba "Follow-up" em /campanhas)

## Contexto e escopo

"Criar cadências" visualmente JÁ existe: o builder React Flow em
`/campanhas/cadencias/[id]` (tabelas `campaigns`/`campaign_nodes`). O que é invisível
para a operação é o MOTOR de follow-up da Valéria (`follow_up_jobs`: cadência 4-touch,
nudge outbound, reaberturas `awaiting_reopen`, retornos agendados) — hoje só uma
timeline por lead dentro de Conversas (`cadence-timeline.tsx`). Este projeto entrega a
visão GLOBAL operacional e gerenciável desse motor.

## Alternativas avaliadas

1. **Página nova no sidebar (/cadencias)** — mais descobrível, mas duplica navegação
   com a aba "Cadências" existente (builder) e confunde os dois sistemas.
2. **Enriquecer só a timeline por lead** — não atende à visão global da diretriz.
3. **Nova aba "Follow-up" dentro de /campanhas** — ESCOLHIDA: integra onde a operação
   já vive (o subtítulo da página já diz "Disparos e cadências de follow-up"), reusa o
   padrão de abas via `?tab=`, zero mudança de sidebar.

## Componentes

### Backend (FastAPI)
- Novo router `backend/app/follow_up/api.py`, prefixo `/api/cadence`:
  - `GET /definition` — serializa a fonte de verdade `follow_up/cadence.py`: toques da
    CADENCE (sequence, offset em horas, jitter, objetivo, rótulo), OUTBOUND_NUDGE,
    MIN_GAP (horas) e a janela comercial (09h–16h BRT, seg–sex). Somente leitura.
- Registro em `main.py`. Teste pytest do shape do payload.

### Frontend — rotas Next (padrão Supabase service, como `api/broadcasts`)
- `GET /api/followups?status=&limit=` — lista `follow_up_jobs` com join
  `leads(name, phone)`; filtro por status (`pending|awaiting_reopen|sent|cancelled`),
  ordenação: pending/awaiting_reopen por `fire_at` asc; sent/cancelled por
  `sent_at|fire_at` desc; limite default 100 (máx 200).
- `GET /api/followups/summary` — contagens: pending, awaiting_reopen, sent hoje (BRT)
  e sent últimos 7 dias (cancelamento não tem timestamp próprio na tabela — KPI de
  cancelados hoje seria mentiroso).
- `POST /api/followups/[id]/cancel` — atualização GUARDADA: só `pending` ou
  `awaiting_reopen` viram `cancelled` com `cancel_reason='cancelled_by_operator'`
  (update com `.in_("status", [...])`; 0 linhas → 409). Nunca toca jobs
  sent/processing.
- `GET /api/cadence/definition` — proxy ao FastAPI (mesmo padrão de
  `api/automation/[...path]`).

### Frontend — UI
- `frontend/src/components/campaigns/followup-board.tsx` (client component):
  1. **Esteira da cadência** (definição): cartões T1→T4 + nudge com offset humano
     ("mesmo dia +1h30–3h30", "D+1", "D+3", "D+6", "+18h") e objetivo — dados do
     endpoint de definição (nunca hardcode que derive de cadence.py).
  2. **KPIs**: Pendentes / Aguardando reabertura / Enviados hoje / Enviados (7 dias).
  3. **Tabela de jobs**: chips de filtro por status; colunas Lead (nome ou telefone,
     link `/conversas?lead_id=`), Toque (seq + objetivo via `objectiveLabel`, ou tipo
     especializado rotulado: handoff_rescue→"Resgate handoff", lp_welcome→"Boas-vindas
     LP", ai_scheduled_return→"Retorno agendado"), Situação (`touchStateLabel`),
     Quando (fire_at/sent_at em BRT), ação **Cancelar** (só pending/awaiting_reopen,
     com confirmação; otimista + refetch).
- `campanhas/page.tsx`: `VALID_TABS` ganha `"follow-up"`, rótulo "Follow-up", render
  `<FollowupBoard />`. Nenhuma alteração de sidebar.
- Helpers puros em `frontend/src/lib/followup-board.ts` (rótulos de tipo, predicado
  `isCancellable`, formatação de datas BRT, rótulo humano de offset) + testes vitest.
  Nota: `isCadenceTouch` de `cadence-display.ts` assume `job_type == null`, mas o
  motor grava `job_type='standard'` — o board trata `standard|null` como toque de
  cadência via helper próprio, sem alterar a lib existente.

## Dados e invariantes
- `env_tag` = `APP_ENV` em todas as queries (paridade com campaigns/broadcasts).
- Cancelamento NUNCA rebaixa job enviado; `processing` (claim do worker) não é
  cancelável pela UI (o claim atômico do worker vence corridas).
- O worker já é event-driven + tick: cancelar um pending basta (o tick pula
  cancelled); nenhuma mudança no motor.

## Erros
- Rotas Next devolvem `{error}` com status apropriado (500 Supabase, 409 guarda).
- Board: estados vazio/carregando/erro explícitos; ação de cancelar mostra erro em
  toast simples (padrão alert/toast local da página de campanhas).

## Testes
- pytest: payload de `/api/cadence/definition` (toques, nudge, min_gap, janela).
- vitest: helpers puros do board.
- `npm run type-check` + `npm run build` (gate de CI existente roda pytest+vitest).
- Smoke pós-deploy: `GET https://api.canastrainteligencia.com/api/cadence/definition`.

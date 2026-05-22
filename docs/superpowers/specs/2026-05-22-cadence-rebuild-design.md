# Cadence Rebuild — Sistema Unificado de Cadência tipo n8n

**Branch:** `feat/cadence-rebuild`
**Data:** 2026-05-22
**Abordagem aprovada:** B (unificar + expandir blocos pro CRM)

---

## Problema

O sistema de cadência atual está fragmentado em dois mundos paralelos no mesmo repo:

- **Sistema legado** — tabelas `cadences`, `cadence_steps`, `cadence_enrollments`; backend `app/cadence/`; rotas `/api/cadences/*`. Linear, sem grafo.
- **Sistema novo** — tabelas `campaigns`, `campaign_nodes`, `campaign_enrollments`; backend `app/automation/` + `app/campaigns/`; rotas `/api/campaigns/*` + `/api/automation/*`. Grafo n8n-like.

O builder (`cadence-flow-builder.tsx`) opera no novo. Mas a tabela de inscritos da mesma cadência (`cadence-enrollments-table.tsx`) lê do legado, que foi **esvaziado** pela migration `20260521_migrate_cadence_enrollments.sql`. Resultado: o usuário monta um fluxo, ativa, e o painel de inscritos fica vazio. "Os dados parecem não se comunicar" — porque literalmente não falam.

Adicionalmente, o plano de ontem (`2026-05-22-cadence-channel-testmode.md`) deixou o modo de teste SSE pela metade — backend existe, frontend tem UI, mas faltam o proxy `/api/automation/:path*` no Next, a migration `channel_id` confirmada, e validação E2E. Por isso "nenhum teste funciona".

Por fim, os blocos disponíveis (condições/ações) não exploram o CRM rico que existe (deals, sales, tags, stages do pipeline, users, broadcasts, messages). Faltam ações estratégicas como "marcar deal ganho", "criar tarefa", "atribuir vendedor", e triggers úteis como "palavra-chave recebida".

## Objetivo

Sistema de cadência único, funcional 100%, com builder estilo n8n: trigger → send → wait → condition (if/else) → end, modo de teste ao vivo com SSE, dados batendo no DB, e nós ricos baseados no CRM real.

## Não-objetivo (out of scope nesta entrega)

- Branches paralelos com merge (split/join)
- Variáveis/expressões dinâmicas em qualquer campo (`{{deal.valor * 0.1}}`)
- Múltiplos triggers por cadência
- Sub-workflows
- Histórico de execuções tipo n8n
- Webhooks externos como trigger
- Triggers agendados (cron)

Esses ficam para futura iteração C (reescrita arquitetural).

---

## Arquitetura

```
┌─ Frontend (Next.js App Router) ────────────────────────────┐
│                                                            │
│  /campanhas                                                │
│   └─ Lista (cadence-list) + modal cria com canal           │
│                                                            │
│  /campanhas/cadencias/[id]                                 │
│   └─ cadence-flow-builder                                  │
│       ├─ Canvas (React Flow)                               │
│       ├─ Inspector (config por nó + override canal)        │
│       ├─ Painel Teste SSE (cores ao vivo + log por nó)     │
│       └─ Painel Inscritos (campaign_enrollments)           │
│                                                            │
│  /api/campaigns/[id]/enrollments  (CRUD inscritos novo)    │
│  /api/automation/[..path]         (proxy SSE → FastAPI)    │
│                                                            │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─ Backend (FastAPI) ────────────────────────────────────────┐
│                                                            │
│  POST /api/automation/trigger                              │
│   └─ fire_trigger() → cria enrollment                      │
│                                                            │
│  GET  /api/automation/campaigns/{id}/test  (SSE)           │
│   └─ test_runner.run_test_campaign() yields data: events   │
│                                                            │
│  scheduler tick (a cada N segundos) →                      │
│   engine.process_due_enrollments()                         │
│    └─ _process_one(enrollment)                             │
│        ├─ send_text | send | wait | condition | action | end
│        └─ avança current_node_id                           │
│                                                            │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─ Postgres / Supabase ──────────────────────────────────────┐
│  campaigns(id, name, channel_id, status, priority,         │
│            frequency_cap, send_start_hour, send_end_hour)  │
│  campaign_nodes(id, campaign_id, type, config jsonb,       │
│                 next_node_id, yes_node_id, no_node_id,     │
│                 position_x, position_y)                    │
│  campaign_enrollments(id, campaign_id, lead_id,            │
│                       current_node_id, status,             │
│                       next_execute_at, retry_count, ...)   │
│  lead_daily_sends(lead_id, date, count)                    │
│                                                            │
│  ❌ DROPPED: cadences, cadence_steps, cadence_enrollments  │
└────────────────────────────────────────────────────────────┘
```

---

## Mudanças por camada

### 1. Banco — migration única de cleanup

**Arquivo:** `supabase/migrations/20260522_cadence_unify_drop_legacy.sql`

```sql
-- Confirma channel_id em campaigns (idempotente)
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;

-- Drop tabelas legadas (já esvaziadas pela migration 20260521)
DROP TABLE IF EXISTS cadence_enrollments CASCADE;
DROP TABLE IF EXISTS cadence_steps CASCADE;
DROP TABLE IF EXISTS cadences CASCADE;
```

A migration `20260522_campaign_channel.sql` que existe ainda **NÃO** deve ser usada como está — ela apaga campanhas existentes. Substituir/sobrescrever por esta versão idempotente que preserva dados do sistema novo.

### 2. Backend — engine, actions, triggers expandidos

**Arquivo:** `backend/app/automation/engine.py`

**Novos `action_type` em `_execute_action`:**

| action_type | Comportamento |
|---|---|
| `mark_deal_won` | Marca último deal do lead como ganho (`stage_id` → stage ganho do pipeline). Cria `sales` row se `cfg.create_sale=true`. |
| `mark_deal_lost` | Marca último deal como perdido. |
| `move_deal_stage` | Move último deal do lead para `cfg.deal_stage_id` (diferente do `move_stage` atual que mexe no `lead.stage`). |
| `create_task` | Insere row em `tasks` (se tabela existir; senão criar). Campos: `title_template`, `due_in_days`, `assigned_to`. |
| `add_note` | Insere row em `lead_notes` com `cfg.note_template` substituído. |
| `notify_user` | Cria notificação para `cfg.user_id` (usar infra existente de notificações; fallback: log). |
| `assign_round_robin` | Pega lista `cfg.user_ids[]`, atribui ao próximo da fila. Estado: coluna `last_assigned_index INT` em `campaigns` (migration adiciona). |

**Novos `trigger_type` em `app/automation/triggers.py`:**

| trigger_type | Disparo |
|---|---|
| `keyword_received` | Disparado pelo webhook do WhatsApp quando `msg.body.toLowerCase()` contém qualquer keyword em `cfg.keywords[]`. |
| `broadcast_finished` | Disparado pelo worker de broadcast ao concluir. Cadência itera sobre `recipient_lead_ids`. |

**Schema de config dos novos action_types** ficará documentado em `backend/app/automation/SCHEMAS.md` (referência para o frontend Inspector).

### 3. Backend — test_runner reflete novos actions

`backend/app/automation/test_runner.py::_execute_test_node` ganha branch para cada novo `action_type`. Em modo teste, ações que alteram dados (`create_task`, `add_note`, `mark_deal_won`, etc.) **não persistem** — apenas logam "ação simulada". Envios continuam reais (este é o ponto do teste).

### 4. Backend — limpeza do legado

- Deletar diretório completo: `backend/app/cadence/`
- Remover import e router include em `backend/app/main.py`
- Remover qualquer chamada cross-module para `app.cadence.*` (grep antes)

### 5. Frontend — proxy SSE

**Arquivo:** `frontend/src/proxy.ts`

Adicionar `/api/automation/:path*` ao matcher. Garantir que o handler suporta `text/event-stream` (não consumir o body, fazer stream).

Caso o middleware proxy não consiga fazer SSE corretamente, criar route handler dedicado:

**Arquivo:** `frontend/src/app/api/automation/[...path]/route.ts` (novo)

```ts
export async function GET(req: NextRequest, { params }) {
  const upstream = await fetch(`${FASTAPI_URL}/api/automation/${params.path.join("/")}${req.nextUrl.search}`, {
    headers: { /* propagate auth */ },
  });
  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
    },
  });
}
```

### 6. Frontend — rotas novas para enrollments

**Arquivo:** `frontend/src/app/api/campaigns/[id]/enrollments/route.ts` (novo)
- `GET` → lista enrollments com join em `leads(id, name, phone, company)` e `campaign_nodes(type, config)` para mostrar nó atual.
- Filtro por `env_tag`.

**Arquivo:** `frontend/src/app/api/campaigns/[id]/enrollments/[enrollId]/route.ts` (novo)
- `PATCH { action: "pause" | "resume" }` → atualiza `status`.
- `DELETE` → soft delete (status → `removed`) ou hard delete via flag.

### 7. Frontend — reescrita do painel de inscritos

**Arquivo:** `frontend/src/components/campaigns/cadence-enrollments-table.tsx`

Trocar:
- Fetch: `/api/cadences/${id}/enrollments` → `/api/campaigns/${id}/enrollments`
- Realtime: `cadence_enrollments` → `campaign_enrollments`
- Prop renomeada: `cadenceId` → `campaignId`
- Adaptar tipos: `CadenceEnrollment` → tipo novo (definir em `lib/types.ts`)

### 8. Frontend — limpeza do legado

Deletar arquivos:
- `frontend/src/app/api/cadences/` (árvore inteira)
- `frontend/src/app/api/leads/[id]/cadence-enrollments/`
- `frontend/src/hooks/use-realtime-cadences.ts`
- `frontend/src/components/campaigns/cadence-steps-table.tsx`
- `frontend/src/app/(authenticated)/campanhas/[id]/page.tsx` (legado — substituído por `/cadencias/[id]/page.tsx`)

Auditar e ajustar:
- `frontend/src/components/leads/lead-detail-modal.tsx` — qualquer fetch a `/api/leads/.../cadence-enrollments` vira `/api/leads/.../campaign-enrollments` (criar rota nova)
- `frontend/src/components/conversas/window-reactivate-panel.tsx` — mesma coisa

Remover tipos obsoletos de `lib/types.ts`: `Cadence`, `CadenceEnrollment`, `CadenceStep`.

### 9. Frontend — Inspector com novos blocos

**Arquivo:** `frontend/src/components/campaigns/cadence-flow-builder.tsx`

Adicionar entradas em `ACTION_LABELS` e `ACTION_ICONS` para os novos action_types. Adicionar configuração visual no Inspector — cada action_type tem seu próprio bloco de campos:

- `mark_deal_won`: checkbox "Criar venda?" + dropdown stage ganho
- `move_deal_stage`: dropdown de stage de deal
- `create_task`: input título (com `{{lead.name}}`), número de dias para vencer, dropdown de usuário
- `add_note`: textarea
- `notify_user`: dropdown de usuário + textarea de mensagem
- `assign_round_robin`: multi-select de usuários

Triggers novos no menu de quick-add:
- `keyword_received`: input com tags de keywords (chips)
- `broadcast_finished`: dropdown de broadcast

### 10. Validação visual de nós inválidos

No Inspector + no canvas:
- Nó `send`/`send_text` sem template/texto E sem canal resolvível → borda vermelha + tooltip "Configure template/texto e canal"
- Nó `condition` sem `condition_type` → idem
- Botão "Ativar campanha" desabilitado se houver nós inválidos
- Botão "Testar" desabilitado se nenhum nó `send`/`send_text` existir

---

## Testes

### Backend
- `backend/tests/test_automation_engine_channel.py` — `_resolve_channel` (já planejado)
- `backend/tests/test_automation_test_runner.py` — sequência linear, format SSE (já planejado)
- `backend/tests/test_automation_actions.py` — **novo** — um teste por action_type novo, mockando supabase
- `backend/tests/test_automation_triggers_new.py` — **novo** — `keyword_received` e `broadcast_finished`

### Frontend
- `npx tsc --noEmit` deve passar limpo
- `npm run build` deve passar limpo

### Manual E2E (checklist na execução)
- [ ] Criar cadência com canal selecionado
- [ ] Adicionar nós trigger → send_text → wait → condition → end
- [ ] Configurar todos os nós sem erros visuais
- [ ] Botão "Testar" com número real → SSE roda nó a nó com cores ao vivo
- [ ] Painel de log mostra duração e mensagem por nó
- [ ] Ativar campanha → criar enrollment manualmente (ou aguardar trigger)
- [ ] Painel de inscritos mostra o enrollment com nó atual
- [ ] Pausar/retomar/remover enrollment funciona
- [ ] Engine roda no scheduler e avança o nó (smoke real em dev)

---

## Plano de migração / rollout

1. **Branch `feat/cadence-rebuild`** já criada
2. Implementar em fases (vide writing-plans skill na sequência):
   - Fase 1: backend engine + actions novos + testes
   - Fase 2: backend cleanup legado + migration
   - Fase 3: frontend rotas novas + proxy + reescrita enrollments table
   - Fase 4: frontend cleanup legado + builder Inspector com novos blocos
   - Fase 5: smoke E2E em dev
3. Commit por fase
4. Usuário testa em dev
5. Push para `master` após autorização (GitHub Actions deploya)

---

## Riscos

| Risco | Mitigação |
|---|---|
| Deletar legado quebra callsite oculto | Grep exaustivo (`from\("cadences\|cadence_"`, `/api/cadences`, `import.*cadence`) antes de cada deleção |
| `EventSource` SSE não passa via proxy Next | Route handler dedicado `/api/automation/[...path]` que faz `fetch` stream e retorna `Response(upstream.body)` |
| `assign_round_robin` precisa de estado persistente | Coluna `last_assigned_index INT DEFAULT -1` em `campaigns` na migration |
| Migration drop apaga dados úteis acidentalmente | Tabelas legadas já estão vazias (migration 20260521 marcou tudo como completed); validar com `SELECT COUNT(*)` antes de DROP |
| Test runner com `send` real cobra crédito Meta | `test_runner` continua mandando mensagem real (decisão prévia do plano de ontem) — usuário escolhe número de teste consciente disso |

---

## Critério de aceitação ("100% funcionando")

- ✅ `git grep -E "cadences|cadence_steps|cadence_enrollments"` retorna apenas a migration de drop
- ✅ Todos os testes backend passam
- ✅ `npx tsc --noEmit` limpo
- ✅ E2E manual passa todos os itens do checklist acima
- ✅ Nenhuma rota `/api/cadences/*` existe
- ✅ Painel de inscritos dentro de uma cadência mostra dados reais de `campaign_enrollments`
- ✅ Botão "Testar" no builder mostra animação ao vivo + log E mensagem chega no WhatsApp

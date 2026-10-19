# Repasse, SLA, 1ª resposta, disparo e custo por closer — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: superpowers:subagent-driven-development (ou executing-plans). Passos com checkbox (`- [ ]`). TDD: teste falhando → código mínimo → teste verde → commit.

**Objetivo:** implementar a spec `docs/superpowers/specs/2026-10-19-repasse-sla-closer-design.md` (B3, B5, B6, B7, B11) no branch `agente/7b143561`, sem publicar.

**Arquitetura:** a fonte do "1º repasse" no SQL é a mensagem de sistema `[encaminhar\_humano] Lead encaminhado%` (já existe em todo o histórico, não depende de backfill); o evento `lead_events.event_type='repasse'` é o histórico estruturado (linha do tempo, /trafego). Uma migration aditiva cria `fn_minutos_uteis_vendedor`, `vw_repasse_resposta`, o trigger de `leads.first_response_at` e troca o SLA/handoffs de `dashboard_kpis`. Backend grava o evento nos dois caminhos de repasse, para de mover card terminal em disparo e conta closer por evento. Frontend lê a view e grava modelo do vendedor como `seller`.

**Stack:** Python 3 / FastAPI / supabase-py (backend, pytest), Next.js App Router + vitest (frontend), Postgres 17 (Supabase self-hosted; testes SQL em container descartável na VPS).

**Worktree:** `C:\Users\rafae\OneDrive\Desktop\Canastra Inteligencia\Agentes AI\ValerIA\.claude\worktrees\agente-7b143561`. Rodar tudo dali. Nunca `git push`, nunca merge em master, nunca escrever no banco de produção (só SELECT).

## Decisão técnica registrada (desvio pequeno da spec, mesmo resultado)
- `vw_repasse_resposta`, o trigger e `dashboard_kpis` tomam o 1º repasse da **mensagem-marcador** (min `created_at` por lead), não de `lead_events`. Motivo: funcionam desde o deploy, antes do backfill R1, e batem com `analytics.vw_repasses`. O evento `repasse` alimenta a linha do tempo e o /trafego (`_closer_ids`).
- `_closer_ids` mantém a coorte do relatório (leads criados no período) e conta quem tem evento `repasse` (qualquer data ≥ criação). É o que a métrica "custo por closer" da coorte mede.

## Mapa de arquivos
| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `supabase/migrations/20261019_repasse_sla.sql` | criar | função de minutos úteis, view, trigger, `dashboard_kpis`, grants |
| `scripts/repasse_sla/rollback_migration.sql` | criar | desfaz a migration |
| `scripts/repasse_sla/r1_eventos_repasse.sql`, `r2_first_response.sql`, `r3_deals_fechado_ganho.sql` (+ `*_rollback.sql`) | criar | backfills com teto |
| `backend/tests/test_repasse_sla_pg.py` | criar | testes SQL contra Postgres descartável |
| `backend/app/leads/repasse.py` | criar | `registrar_repasse` (fail-soft) |
| `backend/app/agent/tools.py` (`_t_encaminhar_humano`) | modificar | chama `registrar_repasse` |
| `backend/app/button_flow/effects.py` (`_aplicar_handoff`) | modificar | chama `registrar_repasse`, `at` em BRT |
| `backend/app/broadcast/worker.py` (~l.1830-1870) | modificar | não move deal terminal |
| `backend/app/campaigns/traffic_report.py` (`_closer_ids`, `_CLOSER_STAGE_KEY`) | modificar | closer = evento repasse |
| `backend/app/watchdog/service.py` (`check_handoff_sla`) | modificar | resposta em qualquer conversa + horário do vendedor |
| `backend/tests/test_repasse_evento.py`, `test_broadcast_terminal_deals.py`, `test_closer_ids_repasse.py`, `test_watchdog_handoff_sla_lead.py` | criar | unit |
| `frontend/src/app/api/conversations/[id]/send-template/route.ts` | modificar | `sent_by='seller'` + `metadata.template` |
| `frontend/src/lib/sla-rounds.ts` | modificar | só `seller` fecha rodada |
| `frontend/src/lib/repasse-resposta.ts` | criar | lê `vw_repasse_resposta` |
| `frontend/src/components/kanban-metrics-bar.tsx`, `conversas/tabs/crm-metricas-tab.tsx`, `leads/lead-detail-modal.tsx`, `lib/lead-overview.ts` | modificar | tempo até 1ª resposta pela view |
| `frontend/src/components/leads/lead-timeline.tsx` | modificar | card "Repassado ao closer" |
| `frontend/src/components/campaigns/broadcast-detail.tsx` (~l.726) | modificar | rótulo neutro |

Tarefas 1–6 são independentes (arquivos disjuntos) e rodam em paralelo. A 7 depende da 1. A 8 fecha tudo.

---

### Tarefa 1: Migration + testes SQL (Postgres descartável)

**Arquivos:** criar `supabase/migrations/20261019_repasse_sla.sql`, `scripts/repasse_sla/rollback_migration.sql`, `backend/tests/test_repasse_sla_pg.py`, `scripts/repasse_sla/scratch_pg.md`.

- [ ] **Passo 1: Subir o Postgres descartável na VPS (só leitura em produção).**
```bash
ssh -i "C:\Users\rafae\.ssh\agente_crm" root@173.249.15.11
docker run -d --rm --name crm-scratch-pg-7b143561 -e POSTGRES_PASSWORD=scratch supabase/postgres:17.6.1.136
# esperar pg_isready; o schema vem SEM dados:
P=$(docker ps -q -f name=supabase_db | head -1)
docker exec $P pg_dump -U postgres --schema-only -n public -n analytics > /tmp/schema_7b143561.sql
docker exec -i crm-scratch-pg-7b143561 psql -U postgres -c "create database p7"
# criar papéis que faltarem (anon, authenticated, service_role, consulta_ro) antes de restaurar; restaurar com ON_ERROR_STOP=0 e conferir que leads/messages/lead_events/deals/pipeline_stages/sla_seller_config/sla_overrides/dashboard_kpis existem.
```
Registrar em `scripts/repasse_sla/scratch_pg.md` o comando exato de psql para os testes (ex.: `ssh … docker exec -i crm-scratch-pg-7b143561 psql -U postgres -d p7`) e como remover (`docker stop crm-scratch-pg-7b143561`). Nunca rodar nada de escrita no `supabase_db`.

- [ ] **Passo 2: Escrever `backend/tests/test_repasse_sla_pg.py` no padrão de `backend/tests/test_cs_p3_timeline_pg.py`** (env `REPASSE_PSQL` com o comando psql; pula sem ele; cada cenário numa transação com ROLLBACK; roda com `python3 backend/tests/test_repasse_sla_pg.py`). Cenários (cada um semeia lead, conversas VALERIA/JOÃO, mensagens):
  1. Repasse (system marker) na conversa A às 10:00 BRT de uma terça; `seller` na conversa B às 10:30 → `leads.first_response_at` = 10:30; `vw_repasse_resposta.minutos_uteis = 30`, `respondeu = true`.
  2. `agent`, `followup`, `broadcast` e `seller` com `message_type='reaction'` depois do repasse → `first_response_at` continua NULL.
  3. `seller` ANTES do repasse → NULL; depois, um `seller` pós-repasse → preenche com o pós.
  4. Segundo `seller` não sobrescreve (COALESCE).
  5. `fn_minutos_uteis_vendedor(NULL, sex 15:00 BRT, seg 10:30 BRT)` = 90 (60 sex + 30 seg); com `sla_seller_config` do usuário 540–1080 → 180+90=270 (sex 15→18 + seg 9→10:30); com `sla_overrides` cobrindo a segunda → 180.
  6. `dashboard_kpis('<data>','<data>')` no período do cenário 1: `handoffs = 1`, `sla_samples = 1`, `sla_median_minutes = 30`; mesmas colunas de saída que antes (comparar `pg_get_function_result`).
  7. Lead com 2 repasses: view usa o 1º.
  8. Insert de mensagem não falha mesmo se o UPDATE do trigger falhar (simular com lead inexistente? usar `lead_id` NULL → trigger não faz nada, insert passa).

- [ ] **Passo 3: Rodar e ver falhar** (`REPASSE_PSQL="…" python3 backend/tests/test_repasse_sla_pg.py` → falha por função/view inexistente).

- [ ] **Passo 4: Escrever a migration** `supabase/migrations/20261019_repasse_sla.sql`:
```sql
-- 20261019_repasse_sla.sql — cartão 7b143561 (spec 2026-10-19-repasse-sla-closer-design.md)
-- NÃO É APLICADA PELO DEPLOY. Aplicar à mão ANTES do push. Só aditiva + CREATE OR REPLACE de dashboard_kpis.
-- Reexecutar é seguro. Depois: recarregar o cache do PostgREST com SIGUSR1.
SET LOCAL lock_timeout = '5s';

-- 1. Minutos dentro do horário do vendedor (sla_seller_config; padrão 10h-16h seg-sex; sla_overrides = dia fora)
CREATE OR REPLACE FUNCTION public.fn_minutos_uteis_vendedor(p_user uuid, p_de timestamptz, p_ate timestamptz)
RETURNS numeric LANGUAGE sql STABLE SET search_path = public AS $$
  WITH cfg AS (
    SELECT COALESCE((SELECT c.window_start_minute FROM sla_seller_config c WHERE c.user_id = p_user AND c.active ORDER BY c.updated_at DESC NULLS LAST LIMIT 1), 600) AS ini,
           COALESCE((SELECT c.window_end_minute   FROM sla_seller_config c WHERE c.user_id = p_user AND c.active ORDER BY c.updated_at DESC NULLS LAST LIMIT 1), 960) AS fim,
           COALESCE((SELECT c.active_weekdays     FROM sla_seller_config c WHERE c.user_id = p_user AND c.active ORDER BY c.updated_at DESC NULLS LAST LIMIT 1), ARRAY[1,2,3,4,5]) AS dias
  ), t AS (
    SELECT (p_de AT TIME ZONE 'America/Sao_Paulo') AS t0, (p_ate AT TIME ZONE 'America/Sao_Paulo') AS t1
  )
  SELECT CASE WHEN p_de IS NULL OR p_ate IS NULL OR p_ate <= p_de THEN 0::numeric ELSE
    round(COALESCE(sum(GREATEST(0::numeric, EXTRACT(epoch FROM (
        LEAST(t.t1, d.d + make_interval(mins => cfg.fim)) - GREATEST(t.t0, d.d + make_interval(mins => cfg.ini)))))), 0) / 60.0, 1) END
  FROM cfg, t
  LEFT JOIN LATERAL generate_series(date_trunc('day', t.t0), date_trunc('day', t.t1), interval '1 day') d(d) ON true
  WHERE d.d IS NULL OR (
        EXTRACT(dow FROM d.d)::int = ANY (cfg.dias)
    AND NOT EXISTS (SELECT 1 FROM sla_overrides o WHERE o.user_id = p_user AND d.d::date BETWEEN o.start_date AND o.end_date))
  GROUP BY t.t0, t.t1;
$$;
```
(Se o agregado com `LEFT JOIN … WHERE` devolver NULL quando nenhum dia conta, envolver em `COALESCE(…, 0)`; o teste 5 pina o valor.)

```sql
-- 2. leads.first_response_at = 1ª mensagem seller (sem reação) depois do 1º repasse, qualquer conversa (D4/D6)
CREATE OR REPLACE FUNCTION public.fn_leads_first_response() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NEW.sent_by = 'seller' AND COALESCE(NEW.message_type, '') <> 'reaction' AND NEW.lead_id IS NOT NULL THEN
    BEGIN
      UPDATE leads l SET first_response_at = NEW.created_at
       WHERE l.id = NEW.lead_id AND l.first_response_at IS NULL
         AND EXISTS (SELECT 1 FROM messages h
                      WHERE h.lead_id = NEW.lead_id AND h.role = 'system'
                        AND h.content LIKE '[encaminhar\_humano] Lead encaminhado%'
                        AND h.created_at <= NEW.created_at);
    EXCEPTION WHEN others THEN
      RAISE WARNING 'fn_leads_first_response: lead %: %', NEW.lead_id, SQLERRM;
    END;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_leads_first_response ON public.messages;
CREATE TRIGGER trg_leads_first_response AFTER INSERT ON public.messages
  FOR EACH ROW EXECUTE FUNCTION public.fn_leads_first_response();

-- 3. Uma linha por lead repassado
CREATE OR REPLACE VIEW public.vw_repasse_resposta WITH (security_invoker = true) AS
WITH r AS (
  SELECT h.lead_id, min(h.created_at) AS repasse_em
    FROM messages h
   WHERE h.role = 'system' AND h.content LIKE '[encaminhar\_humano] Lead encaminhado%' AND h.lead_id IS NOT NULL
   GROUP BY h.lead_id
), x AS (
  SELECT r.lead_id, r.repasse_em,
         COALESCE((SELECT (e.metadata->>'vendedor_id')::uuid FROM lead_events e
                    WHERE e.lead_id = r.lead_id AND e.event_type = 'repasse' AND e.metadata->>'vendedor_id' ~ '^[0-9a-f-]{36}$'
                    ORDER BY e.occurred_at LIMIT 1), l.assigned_to) AS vendedor_id,
         l.first_response_at AS primeira_resposta_em
    FROM r JOIN leads l ON l.id = r.lead_id
)
SELECT x.lead_id, x.repasse_em, x.vendedor_id, x.primeira_resposta_em,
       CASE WHEN x.primeira_resposta_em IS NOT NULL THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, x.primeira_resposta_em) END AS minutos_uteis,
       CASE WHEN x.primeira_resposta_em IS NULL THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, now()) END AS minutos_uteis_em_aberto,
       (x.primeira_resposta_em IS NOT NULL) AS respondeu
  FROM x;
```
(Se `leads.assigned_to` não for uuid no schema, ajustar o cast; conferir com `\d leads`.)

  4. `dashboard_kpis`: copiar a função **inteira** de `supabase/migrations/20260712_dashboard_rpcs.sql` (mesma assinatura, mesmo `RETURNS TABLE`, `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public`) e trocar só:
```sql
  handoff_msgs AS (   -- D3: 1º repasse do lead, caindo no período
    SELECT r.lead_id, r.repasse_em AS created_at
      FROM vw_repasse_resposta r, bounds
     WHERE r.repasse_em >= bounds.s AND r.repasse_em < bounds.e
  ),
  ...
  sla AS (            -- D4: resposta seller em qualquer conversa, horário do vendedor
    SELECT r.minutos_uteis * 60.0 AS busy_secs
      FROM vw_repasse_resposta r, bounds
     WHERE r.repasse_em >= bounds.s AND r.repasse_em < bounds.e AND r.respondeu
  ),
```
     Atualizar o comentário CAVEAT (o SLA agora olha qualquer conversa do lead; mensagens do celular continuam invisíveis). O resto (leads novos, qualificação, custo) idêntico.
  5. Grants:
```sql
GRANT EXECUTE ON FUNCTION public.fn_minutos_uteis_vendedor(uuid, timestamptz, timestamptz) TO authenticated, service_role;
GRANT SELECT ON public.vw_repasse_resposta TO authenticated, service_role;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT EXECUTE ON FUNCTION public.fn_minutos_uteis_vendedor(uuid, timestamptz, timestamptz) TO consulta_ro;
    GRANT SELECT ON public.vw_repasse_resposta TO consulta_ro;
  END IF;
END $$;
```

- [ ] **Passo 5: `scripts/repasse_sla/rollback_migration.sql`**: `DROP TRIGGER IF EXISTS trg_leads_first_response ON public.messages; DROP FUNCTION IF EXISTS public.fn_leads_first_response(); DROP VIEW IF EXISTS public.vw_repasse_resposta; DROP FUNCTION IF EXISTS public.fn_minutos_uteis_vendedor(uuid,timestamptz,timestamptz);` e a definição original completa de `dashboard_kpis` copiada de `20260712_dashboard_rpcs.sql` (ordem: recriar `dashboard_kpis` original ANTES do DROP VIEW, porque a nova depende da view).

- [ ] **Passo 6: Aplicar a migration no scratch, rodar os testes, todos PASS.** Aplicar duas vezes para provar idempotência.

- [ ] **Passo 7: Ensaio só leitura em produção.** Rodar, em `BEGIN READ ONLY; … ROLLBACK;` no `supabase_db`, a CTE da view + SLA para jul–out/2026 (sem criar objetos) e comparar a mediana de out com `select percentile_cont(0.5) within group (order by minutos_uteis) from analytics.vw_resposta_closer where repasse_em >= '2026-10-01' and respondeu` — anotar os números em `scripts/repasse_sla/scratch_pg.md`.

- [ ] **Passo 8: Commit** `git add supabase/migrations/20261019_repasse_sla.sql scripts/repasse_sla backend/tests/test_repasse_sla_pg.py && git commit -m "feat(sla): migration de 1ª resposta, view de repasse e SLA do dashboard por lead (7b143561)"`.

---

### Tarefa 2: Evento `repasse` nos dois caminhos (B3)

**Arquivos:** criar `backend/app/leads/repasse.py`, `backend/tests/test_repasse_evento.py`; modificar `backend/app/agent/tools.py` (`_t_encaminhar_humano`), `backend/app/button_flow/effects.py` (`_aplicar_handoff`).

- [ ] **Passo 1: Teste falhando** `backend/tests/test_repasse_evento.py`:
```python
from unittest.mock import MagicMock
from app.leads import repasse

def _sb_ok():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return sb

def test_registrar_repasse_grava_evento(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    ok = repasse.registrar_repasse(
        lead_id="L1", conversation_id="C1", message_id="M1",
        occurred_at="2026-10-19T10:00:00-03:00", source="ia",
        vendedor_id="U1", vendedor="João", segmento="atacado", motivo="lead qualificado")
    assert ok is True
    sb.table.assert_called_with("lead_events")
    ev = sb.table.return_value.insert.call_args.args[0]
    assert ev["event_type"] == "repasse"
    assert ev["dedupe_key"] == "repasse:M1"
    assert ev["source"] == "ia"
    assert ev["occurred_at"] == "2026-10-19T10:00:00-03:00"
    assert ev["metadata"] == {"vendedor_id": "U1", "vendedor": "João", "segmento": "atacado",
                              "motivo": "lead qualificado", "conversation_id": "C1", "message_id": "M1"}

def test_registrar_repasse_fail_soft(monkeypatch):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    assert repasse.registrar_repasse(lead_id="L1", conversation_id=None, message_id="M1",
                                     occurred_at=None, source="button_flow") is False

def test_sem_message_id_nao_grava(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    assert repasse.registrar_repasse(lead_id="L1", conversation_id="C1", message_id=None,
                                     occurred_at=None, source="ia") is False
    sb.table.assert_not_called()
```
  Mais dois testes de integração com os dublês que já existem nos testes de `_t_encaminhar_humano` e `_aplicar_handoff` (procurar com `grep -rln "_t_encaminhar_humano\|_aplicar_handoff" backend/tests`): (a) depois do repasse, `registrar_repasse` foi chamado com `message_id` = id devolvido pelo `save_message` do marcador, `source` = `ia`/`button_flow`; (b) se `registrar_repasse` levantar, o repasse termina igual (o retorno da tool e o carimbo `metadata.handoff` não mudam). E (c) em `_aplicar_handoff`, `metadata.handoff.at` termina em `-03:00`.

- [ ] **Passo 2: Rodar e ver falhar** `cd backend && python -m pytest tests/test_repasse_evento.py -q`.

- [ ] **Passo 3: Implementar `backend/app/leads/repasse.py`:**
```python
"""Evento `lead_events.repasse`: um por repasse ao closer (D3), sem sobrescrever histórico.

Fail-soft: o repasse em si (mensagem-marcador + carimbo metadata.handoff) já foi gravado e é
o que follow-up, buffer e watchdog leem; perder o evento só empobrece a linha do tempo."""
from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def registrar_repasse(*, lead_id: str, conversation_id: str | None, message_id: str | None,
                      occurred_at: str | None, source: str, vendedor_id: str | None = None,
                      vendedor: str | None = None, segmento: str | None = None,
                      motivo: str | None = None) -> bool:
    if not lead_id or not message_id:
        logger.warning("registrar_repasse: lead %s sem message_id; evento não gravado", lead_id)
        return False
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "repasse",
        "new_value": vendedor,
        "source": source,
        "dedupe_key": f"repasse:{message_id}",
        "metadata": {"vendedor_id": vendedor_id, "vendedor": vendedor, "segmento": segmento,
                     "motivo": motivo, "conversation_id": conversation_id, "message_id": message_id},
    }
    if occurred_at:
        evento["occurred_at"] = occurred_at
    try:
        get_supabase().table("lead_events").insert(evento).execute()
        return True
    except Exception as exc:  # inclui violação do dedupe_key (repetição) — idempotente
        logger.error("registrar_repasse: evento do lead %s não gravado: %s", lead_id, exc)
        return False
```

- [ ] **Passo 4: Ligar em `tools.py`.** Em `_t_encaminhar_humano`, trocar a linha `save_message(lead_id, "system", handoff_system_marker(vendedor, motivo), conversation_id=conversation_id)` por guardar o retorno (`_marker = save_message(...)`) e, **depois** do bloco do carimbo `metadata.handoff`, chamar:
```python
    try:
        from app.leads.repasse import registrar_repasse
        registrar_repasse(lead_id=lead_id, conversation_id=conversation_id,
                          message_id=(_marker or {}).get("id"),
                          occurred_at=(_marker or {}).get("created_at"), source="ia",
                          vendedor_id=_assigned_to, vendedor=vendedor, segmento=_seg, motivo=motivo)
    except Exception as _ev_exc:
        logger.error("encaminhar_humano: evento repasse do lead %s: %s", lead_id, _ev_exc)
```
- [ ] **Passo 5: Ligar em `effects.py`.** Em `_aplicar_handoff`: guardar o retorno do `save_message` do marcador (inicializar `_marker = None` antes do try); no carimbo trocar `datetime.now(timezone.utc).isoformat()` por `datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()` (usar o fuso já importado no módulo se existir; senão `from zoneinfo import ZoneInfo`); depois de `atualizar_metadata(...)` chamar `registrar_repasse(..., source="button_flow", vendedor_id=None, vendedor=vendedor, segmento=lead.get("stage"), motivo=motivo)` dentro de try/except com log.
- [ ] **Passo 6: Testes verdes** (`python -m pytest tests/test_repasse_evento.py tests/ -q -k "encaminhar or handoff or button_flow or repasse"`) e a suíte dos módulos tocados.
- [ ] **Passo 7: Commit** `feat(repasse): evento lead_events 'repasse' nos dois caminhos de repasse (7b143561)`.

---

### Tarefa 3: Disparo não move card terminal (B7)

**Arquivos:** modificar `backend/app/broadcast/worker.py` (bloco "Move lead's deal to configured Kanban stage", ~l.1830-1870); criar `backend/tests/test_broadcast_terminal_deals.py`.

- [ ] **Passo 1: Extrair a lógica para uma função testável no próprio `worker.py`:**
```python
TERMINAL_STAGE_KEYS = ("fechado_ganho", "fechado_perdido", "perdido", "encerrado")

def _mover_deals_do_disparo(sb, lead: dict, pipeline_id: str, stage_id: str) -> bool:
    """Move para a etapa-alvo só os deals ABERTOS do lead no funil (sem closed_at e fora de
    etapa terminal). Sem deal aberto → cria um card novo na etapa-alvo (o ganho/perdido fica
    intacto). Devolve True se algo mudou ou foi criado (é quando se grava deal_moved_at)."""
```
  Implementação: buscar `deals.select("id, closed_at, stage_id").eq("lead_id",…).eq("pipeline_id",…)`; buscar as keys das etapas (`pipeline_stages.select("id,key").in_("id", ids)`); abertos = sem `closed_at` e key fora de `TERMINAL_STAGE_KEYS`; mover só os abertos cujo `stage_id != stage_id alvo` (`.in_("id", ids_abertos)`); se não há aberto algum, inserir o card novo exatamente como o código atual faz (`title`, `stage='novo'`, `pipeline_id`, `stage_id`); se havia abertos mas todos já estavam na etapa-alvo → não muda nada e devolve False.
- [ ] **Passo 2: Testes (falhando primeiro)** com um `sb` dublê que registra chamadas: (a) só deal `fechado_ganho` → nenhum UPDATE em deals, um INSERT, retorno True; (b) deal com `closed_at` em etapa não terminal → tratado como fechado (INSERT, sem UPDATE); (c) um aberto em outra etapa + um ganho → UPDATE só do aberto, sem INSERT, True; (d) aberto já na etapa-alvo → nada, False; (e) `perdido` → não move.
- [ ] **Passo 3: No worker, substituir o bloco** pelo uso de `_mover_deals_do_disparo` e gravar `deal_moved_at` **só** quando ela devolver True. Manter os logs e o `except Exception as move_err` existente.
- [ ] **Passo 4:** `python -m pytest tests/test_broadcast_terminal_deals.py tests/ -q -k broadcast` verde.
- [ ] **Passo 5: Commit** `fix(broadcast): disparo não tira card de fechado ganho/perdido (7b143561)`.

---

### Tarefa 4: Custo por closer pelo evento de repasse (B11)

**Arquivos:** modificar `backend/app/campaigns/traffic_report.py` (`_CLOSER_STAGE_KEY` l.94, `_closer_ids` l.652-670); criar `backend/tests/test_closer_ids_repasse.py`.

- [ ] **Passo 1: Teste falhando:** dublê de `sb` cujo `table("lead_events").select(...).in_("lead_id", chunk).eq("event_type","repasse")` devolve linhas; `_closer_ids(sb, ["A","B","C"])` com eventos de A e C → `{"A","C"}`; lead B com deal em `perdido` e sem evento → fora; lead em funil do João com evento → dentro. Ver no arquivo como `_fetch_all` e `_chunks` são usados e montar o dublê compatível.
- [ ] **Passo 2: Implementar:**
```python
def _closer_ids(sb, lead_ids: list[str]) -> set[str]:
    """D3: closer = lead da coorte com evento lead_events 'repasse' (1º repasse ao closer).
    Não olha etapa de deal: 'perdido' não é closer e os funis do João (sem key
    'qualificado') contam normalmente."""
    out: set[str] = set()
    for chunk in _chunks(lead_ids):
        rows = _fetch_all(lambda c=chunk: sb.table("lead_events").select("lead_id")
                          .in_("lead_id", c).eq("event_type", "repasse"))
        out.update(r["lead_id"] for r in rows if r.get("lead_id"))
    return out
```
  Remover `_CLOSER_STAGE_KEY` se não tiver outro uso (`grep -n _CLOSER_STAGE_KEY`). Atualizar testes existentes de `_closer_ids`/relatório que dependiam da etapa (`grep -rn "_closer_ids\|qualificado" backend/tests/*traffic*`), sem afrouxar o que eles verificam de resto.
- [ ] **Passo 3:** testes do traffic_report verdes. **Commit** `fix(trafego): custo por closer conta lead com repasse (7b143561)`.

---

### Tarefa 5: Watchdog do SLA pós-repasse (B6)

**Arquivos:** modificar `backend/app/watchdog/service.py` (`check_handoff_sla` ~l.509-600); criar `backend/tests/test_watchdog_handoff_sla_lead.py`. Ver testes existentes com `grep -rln check_handoff_sla backend/tests`.

- [ ] **Passo 1: Testes falhando:** (a) conversa no canal humano com cliente às 10:00 e `last_seller_response_at` vazio, mas **outra conversa do mesmo lead** com `last_seller_response_at` 10:05 → sem violação; (b) cliente 15:50 de sexta, agora segunda 10:05, vendedor sem config (padrão 10–16) → 10 + 5 = 15 min úteis → sem violação; às 10:15 → violação (25 min); (c) com `sla_seller_config` 540–1080 do `assigned_to` do lead, cliente 17:50 sexta, agora segunda 9:05 → 10+5=15 → sem violação.
- [ ] **Passo 2: Implementar:**
  - incluir `leads!inner(name, assigned_to)` no select;
  - depois do filtro atual, para os candidatos buscar `conversations.select("lead_id,last_seller_response_at").in_("lead_id", lead_ids)` e considerar respondido se o **máximo** `last_seller_response_at` do lead ≥ `customer_ts`;
  - trocar `now - customer_ts <= sla_threshold` por minutos úteis: nova função pura `_minutos_uteis(inicio, fim, cfg)` (cfg = `{ini, fim, dias}`, padrão 600/960/[1..5], fuso America/Sao_Paulo; `dias` no padrão Postgres `dow` 0=domingo) + `_carregar_cfg_sla(sb, user_ids)` lendo `sla_seller_config` (ativos) e `sla_overrides`; violação se `_minutos_uteis(customer_ts, now, cfg) > HANDOFF_SLA_MINUTES`;
  - manter `_within_sla_window`, o dedup, o escalonamento e o texto do alerta.
- [ ] **Passo 3:** testes do watchdog verdes. **Commit** `fix(watchdog): SLA pós-repasse olha todas as conversas do lead e o horário do vendedor (7b143561)`.

---

### Tarefa 6: Frontend

**Arquivos:** os do mapa (frontend). Ler os padrões de `frontend/src/app` e os testes vitest vizinhos antes. Rodar `cd frontend && npx vitest run <arquivos>`.

- [ ] **6a `send-template/route.ts`:** no insert da mensagem trocar `sent_by: "broadcast"` por `sent_by: "seller"` e adicionar `metadata: { template: true, template_name }`; se a resposta da Meta trouxer `messages[0].id`, gravar `wamid` e `delivery_status: "accepted"` (ver como `react/route.ts` faz). Teste vitest (criar ao lado, no padrão dos testes de rota existentes, `grep -rl "route" frontend/src --include=*.test.ts | head`) verificando o objeto inserido.
- [ ] **6b `sla-rounds.ts`:** `const REPLY_SENDERS = new Set(["seller"]);` e atualizar o comentário (a IA não fecha rodada — D4). Ajustar/adicionar teste em `sla-rounds.test.ts`: mensagem `agent` depois do cliente não fecha a rodada.
- [ ] **6c `lib/repasse-resposta.ts`:**
```ts
import type { SupabaseClient } from "@supabase/supabase-js";

export interface RepasseResposta {
  lead_id: string;
  repasse_em: string;
  vendedor_id: string | null;
  primeira_resposta_em: string | null;
  minutos_uteis: number | null;
  minutos_uteis_em_aberto: number | null;
  respondeu: boolean;
}

/** D4/D6: tempo até o closer assumir, em minutos úteis do vendedor, a partir do 1º repasse. */
export async function fetchRepasseResposta(sb: SupabaseClient, leadIds: string[]): Promise<Map<string, RepasseResposta>> {
  const out = new Map<string, RepasseResposta>();
  for (let i = 0; i < leadIds.length; i += 200) {
    const { data, error } = await sb.from("vw_repasse_resposta").select("*").in("lead_id", leadIds.slice(i, i + 200));
    if (error) throw error;
    for (const r of (data ?? []) as RepasseResposta[]) out.set(r.lead_id, r);
  }
  return out;
}

export function formatarMinutos(m: number | null | undefined): string {
  if (m == null) return "—";
  if (m < 60) return `${Math.round(m)} min`;
  const h = Math.floor(m / 60), r = Math.round(m % 60);
  return r ? `${h}h ${r}min` : `${h}h`;
}
```
  com teste de `formatarMinutos`.
- [ ] **6d Telas:** em `kanban-metrics-bar.tsx`, `conversas/tabs/crm-metricas-tab.tsx`, `leads/lead-detail-modal.tsx` e `lib/lead-overview.ts`, onde hoje se calcula `first_response_at - created_at`, passar a usar `minutos_uteis` da view (média/mediana dos leads com `respondeu` no Kanban; valor do lead na ficha/aba/overview; lead sem linha na view → "—"; rótulo "Tempo até o closer assumir (horário comercial)"). Seguir o jeito de buscar dados de cada componente (client supabase do browser ou rota `/api/...`); se o componente recebe leads por props, buscar a view no mesmo lugar onde os leads são buscados. Atualizar os testes existentes dessas telas.
- [ ] **6e `lead-timeline.tsx`:** novo `case "repasse"`: título "Repassado ao closer", linha com `metadata.vendedor`, `metadata.segmento`, `metadata.motivo` (omitir vazios); atualizar o comentário da l.23 com `repasse`. Teste em `lead-timeline.test.tsx`.
- [ ] **6f `broadcast-detail.tsx` (~l.726-735):** "Card movido no envio" / "Card não movido", ambos em cinza neutro (mesma classe de texto secundário usada no arquivo), sem verde/vermelho. Teste se houver teste do componente; senão, só o build.
- [ ] **6g** `npx vitest run` dos arquivos tocados verde e `npx tsc --noEmit -p .` sem erro novo. **Commits** separados por item (`feat(sla-front): …`).

---

### Tarefa 7: Backfills R1, R2, R3 (só escritos e testados no scratch — NÃO rodar em produção)

**Arquivos:** `scripts/repasse_sla/r1_eventos_repasse.sql`, `r1_rollback.sql`, `r2_first_response.sql`, `r2_rollback.sql`, `r3_deals_fechado_ganho.sql`, `r3_rollback.sql`, `scripts/repasse_sla/README.md`; cenários novos em `backend/tests/test_repasse_sla_pg.py`.

Cada script: `BEGIN; SET LOCAL lock_timeout='5s';` → `RAISE NOTICE` com a contagem prévia → escrita → `DO $$ … IF n > teto THEN RAISE EXCEPTION … END $$` → `RAISE NOTICE` depois → `COMMIT;`. Idempotente.

- [ ] **R1** — insert em `lead_events` de toda mensagem marcador sem evento: `event_type='repasse'`, `source='backfill'`, `occurred_at=m.created_at`, `dedupe_key='repasse:'||m.id`, `new_value` = vendedor do carimbo quando bate, `metadata` = `{vendedor_id: leads.assigned_to, vendedor/segmento/motivo do metadata.handoff só se abs(handoff.at - m.created_at) <= 5 min, conversation_id, message_id}`; `ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING`; teto 2.100 inserções. Rollback: `DELETE FROM lead_events WHERE event_type='repasse' AND source='backfill';`.
- [ ] **R2** — `CREATE TABLE IF NOT EXISTS backup_r2_first_response_20261019(lead_id uuid primary key, first_response_at_anterior timestamptz)`; abortar se algum lead do alvo já tiver valor ≠ NULL; preencher só `IS NULL` com a 1ª `seller` (sem reação) depois da 1ª mensagem marcador; teto 1.900. Rollback: `UPDATE leads l SET first_response_at=b.first_response_at_anterior FROM backup_r2… b WHERE l.id=b.lead_id;`.
- [ ] **R3** — alvo: deals em etapa `chamado_reposicao` com `closed_at` não nulo e `broadcast_leads.deal_moved_at > deals.closed_at` para o mesmo lead; `CREATE TABLE IF NOT EXISTS backup_r3_deals_20261019(deal_id uuid primary key, stage_id_anterior uuid, entered_stage_at_anterior timestamptz)`; `UPDATE deals SET stage_id = <etapa fechado_ganho do mesmo pipeline_id>, entered_stage_at = closed_at`; **abortar se o número ≠ 30** (constante no topo, editável só com novo OK). Rollback pelo backup.
- [ ] **Testes no scratch:** semear dados mínimos e verificar para cada script: escreve o esperado, segunda execução não muda nada, teto aborta (semear acima do teto num cenário), rollback volta ao estado anterior. Para R3 parametrizar o "30" via `current_setting('repasse.r3_esperado', true)` com padrão 30, para o teste usar outro número.
- [ ] **README** com ordem (R1 → R2 → R3), contagem esperada, comando, SQL de aceite da spec e rollback.
- [ ] **Commit** `chore(repasse-sla): backfills R1-R3 com teto e rollback (não aplicados) (7b143561)`.

---

### Tarefa 8: Verificação final

- [ ] `cd backend && python -m pytest -q` (suíte inteira) — anotar totais; nenhuma falha nova vs `git stash`-free baseline (rodar a suíte também em `origin/master` num diretório temporário? não: comparar com a lista de falhas pré-existentes executando a suíte antes das mudanças, registrada no início da execução).
- [ ] `cd frontend && npx vitest run` e `npm run build`.
- [ ] `REPASSE_PSQL=… python3 backend/tests/test_repasse_sla_pg.py` todos PASS; `test_cs_p3_timeline_pg.py` continua passando no scratch.
- [ ] Revisão de código do diff inteiro (superpowers:requesting-code-review).
- [ ] Remover o container scratch (`docker stop crm-scratch-pg-7b143561`) só no fim.

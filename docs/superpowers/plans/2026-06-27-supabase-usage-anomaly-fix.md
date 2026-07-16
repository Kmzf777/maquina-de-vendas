# Correção da Anomalia de Consumo Supabase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interromper o loop de re-disparo de templates que inflou `meta_webhook_logs` (558 MB / 88% do DB) e cortar o over-fetching dos hooks de dashboard que estourou o Egress (5.56 GB), trazendo o projeto para dentro do Free Tier antes do fim do Grace Period (06/jul/2026).

**Architecture:** Três frentes independentes — (1) Backend Python: tornar `_execute_send_node`/`process_campaign_enrollments` resiliente a falhas, cancelando em erro permanente (400/404) e aplicando backoff com teto de 3 via `automation/retry.py`; (2) Banco prod: função de retenção + agendamento `pg_cron` (>15 dias), drop de índice redundante e limpeza inicial dos dados mortos com reclaim de espaço; (3) Frontend Next.js: remover `setInterval(60s)`, debouncar o refetch disparado por Realtime, adicionar cutoff temporal e trocar `SELECT *` por colunas explícitas nos hooks SLA.

**Tech Stack:** Python 3.11 / FastAPI / supabase-py / pytest; PostgreSQL 17 (Supabase) / pg_cron; Next.js App Router / React hooks / vitest.

## Global Constraints

- Fluxo Git: branch `fix/supabase-usage-anomaly`; destino final é `master` no remoto, mas **push para master exige autorização explícita do usuário** (deploy de produção). Este plano só faz **commits na branch local**.
- Paridade de ambiente: o código deve rodar em container e no host sem modificação; nada de `localhost`/IP fixo no código.
- Provedor WhatsApp ativo = **Meta Graph API** (`backend/app/whatsapp/meta.py`). Ignorar Evolution.
- Operações no banco são **estritamente em produção** (`tshmvxxxyxgctrdkqvam` / PROD - DB CANASTRA). Sem `VACUUM FULL` bloqueante sobre tabela grande — purgar primeiro, depois reclaim sobre o remanescente pequeno (justificado por ser tabela de log fire-and-forget).
- `meta_webhook_logs` é log fire-and-forget (`app/meta_audit.py` engole exceções) — escritas concorrentes nunca derrubam o fluxo principal.

---

### Task 1: Resiliência do worker de campanhas (para o loop)

**Files:**
- Modify: `backend/app/campaigns/worker.py` (`process_campaign_enrollments` except + novos helpers; reset de `retry_count` no avanço)
- Test: `backend/tests/test_campaigns_worker_retry.py` (criar)

**Interfaces:**
- Consumes: `app.automation.retry.calculate_next_retry(retry_count:int, now:datetime) -> tuple[datetime,int,bool]`; `app.campaigns.service.update_enrollment(enrollment_id:str, **kwargs) -> dict`
- Produces:
  - `_is_permanent_error(exc: Exception) -> bool`
  - `decide_failure_update(exc: Exception, retry_count: int, now: datetime) -> dict` — retorna kwargs prontos para `update_enrollment` que **sempre** tiram a enrollment do estado imediatamente-due (ou `status="cancelled"`, ou `next_execute_at` no futuro).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_campaigns_worker_retry.py
import httpx
import pytest
from datetime import datetime, timezone, timedelta

from app.campaigns.worker import _is_permanent_error, decide_failure_update

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://graph.facebook.com/v21.0/x/messages")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


class TestIsPermanentError:
    def test_404_is_permanent(self):
        assert _is_permanent_error(_http_error(404)) is True

    def test_400_is_permanent(self):
        assert _is_permanent_error(_http_error(400)) is True

    def test_embedded_rejection_runtimeerror_is_permanent(self):
        exc = RuntimeError("Meta send_template rejected (missing messages in response): {}")
        assert _is_permanent_error(exc) is True

    def test_500_is_not_permanent(self):
        assert _is_permanent_error(_http_error(500)) is False

    def test_generic_exception_is_not_permanent(self):
        assert _is_permanent_error(ValueError("boom")) is False


class TestDecideFailureUpdate:
    def test_permanent_error_cancels(self):
        upd = decide_failure_update(_http_error(404), retry_count=0, now=NOW)
        assert upd["status"] == "cancelled"
        assert "last_error" in upd

    def test_first_transient_failure_schedules_retry_1h(self):
        upd = decide_failure_update(_http_error(500), retry_count=0, now=NOW)
        assert "status" not in upd  # permanece ativa, mas adiada
        assert upd["retry_count"] == 1
        expected = (NOW + timedelta(hours=1)).isoformat()
        assert upd["next_retry_at"] == expected
        assert upd["next_execute_at"] == expected  # tira do estado due

    def test_transient_failure_at_cap_cancels(self):
        upd = decide_failure_update(_http_error(500), retry_count=3, now=NOW)
        assert upd["status"] == "cancelled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_campaigns_worker_retry.py -v`
Expected: FAIL com `ImportError: cannot import name '_is_permanent_error'`

- [ ] **Step 3: Write minimal implementation**

Adicionar no topo de `backend/app/campaigns/worker.py` (após os imports existentes):

```python
from app.automation.retry import calculate_next_retry

# Status HTTP da Meta que não adianta retentar (template/locale/param errados):
# o disparo nunca vai ser aceito — cancelar a enrollment em vez de re-armar.
_PERMANENT_STATUS = {400, 403, 404}


def _is_permanent_error(exc: Exception) -> bool:
    """True para rejeições da Meta que não mudam com retry (4xx de template/param).

    Cobre dois formatos: httpx.HTTPStatusError (raise_for_status em 4xx) e o
    RuntimeError que send_template/send_text levantam quando a Meta devolve HTTP 200
    com erro embutido ('... rejected (missing messages ...)').
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in _PERMANENT_STATUS:
        return True
    if isinstance(exc, RuntimeError) and "rejected" in str(exc):
        return True
    return False


def decide_failure_update(exc: Exception, retry_count: int, now: datetime) -> dict:
    """Pure: kwargs para update_enrollment que SEMPRE tiram a enrollment do estado
    imediatamente-due — raiz do loop que inflou meta_webhook_logs.

    - Erro permanente (4xx / rejeição embutida): status='cancelled'.
    - Erro transitório: backoff via calculate_next_retry (1h/4h/24h, teto 3);
      ao estourar o teto, cancela.
    """
    err = str(exc)[:500]
    if _is_permanent_error(exc):
        return {"status": "cancelled", "last_error": err}
    next_at, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        return {"status": "cancelled", "last_error": err}
    iso = next_at.isoformat()
    return {
        "retry_count": new_count,
        "next_retry_at": iso,
        "next_execute_at": iso,
        "last_error": err,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_campaigns_worker_retry.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Wire into the enrollment loop**

Em `process_campaign_enrollments`, substituir o bloco `except` (atualmente em ~L157-158):

```python
        except Exception as e:
            logger.error("[CAMPAIGNS] Error processing enrollment %s node %s: %s", enrollment["id"], node.get("id"), e, exc_info=True)
```

por:

```python
        except Exception as e:
            logger.error("[CAMPAIGNS] Error processing enrollment %s node %s: %s", enrollment["id"], node.get("id"), e, exc_info=True)
            try:
                upd = decide_failure_update(e, enrollment.get("retry_count") or 0, now)
                update_enrollment(enrollment["id"], **upd)
            except Exception as inner:
                logger.error("[CAMPAIGNS] Failed to record enrollment failure %s: %s", enrollment["id"], inner)
```

E no avanço bem-sucedido (linha do `update_enrollment(... current_node_id=next_id ...)`), adicionar `retry_count=0` para zerar o contador após sucesso:

```python
            if next_id:
                update_enrollment(enrollment["id"], current_node_id=next_id, next_execute_at=now.isoformat(), retry_count=0)
            else:
                complete_enrollment(enrollment["id"])
```

Adicionar `update_enrollment` ao import existente de `app.campaigns.service` no topo (já importado — confirmar que está na lista).

- [ ] **Step 6: Run full backend suite for regressions**

Run: `cd backend && python -m pytest tests/test_campaigns_worker_retry.py tests/test_automation_retry.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/campaigns/worker.py backend/tests/test_campaigns_worker_retry.py
git commit -m "fix(campaigns): cancela enrollment em erro permanente (400/404) e aplica backoff (teto 3) — para o loop de re-disparo"
```

---

### Task 2: Retenção, índice e limpeza de `meta_webhook_logs` (banco prod)

**Files:**
- Create: `backend/migrations/20260627_meta_webhook_logs_retention.sql`
- (Execução em prod via MCP `supabase-prod` — apply_migration + execute_sql)

**Interfaces:**
- Produces: função `public.purge_meta_webhook_logs(retention_days int default 15, batch_size int default 10000) returns integer`; job pg_cron `purge-meta-webhook-logs`.

- [ ] **Step 1: Escrever a migration**

```sql
-- backend/migrations/20260627_meta_webhook_logs_retention.sql
-- Retenção de meta_webhook_logs (15 dias) + drop de índice redundante.
-- Contexto: tabela de log inflou a 558MB (88% do DB) por loop de send_template
-- 400/404 sem política de retenção. Ver docs/superpowers/plans/2026-06-27-supabase-usage-anomaly-fix.md

create extension if not exists pg_cron;

-- Função de purga em lotes (batches) para limitar o tamanho de cada DELETE.
create or replace function public.purge_meta_webhook_logs(
  retention_days int default 15,
  batch_size int default 10000
) returns integer
language plpgsql
as $$
declare
  deleted_total int := 0;
  deleted_batch int;
  cutoff timestamptz := now() - make_interval(days => retention_days);
begin
  loop
    delete from public.meta_webhook_logs
    where ctid in (
      select ctid from public.meta_webhook_logs
      where received_at < cutoff
      limit batch_size
    );
    get diagnostics deleted_batch = row_count;
    deleted_total := deleted_total + deleted_batch;
    exit when deleted_batch = 0;
  end loop;
  return deleted_total;
end;
$$;

-- Agendamento diário às 06:00 UTC (03:00 BRT, baixo tráfego).
select cron.schedule(
  'purge-meta-webhook-logs',
  '0 6 * * *',
  $$select public.purge_meta_webhook_logs(15, 10000);$$
);

-- Drop do índice redundante: idx_meta_webhook_logs_from_number cobre (from_number,
-- received_at) na tabela inteira — mas linhas outbound têm from_number NULL (~398k),
-- então ele indexa quase só NULLs (23MB). O parcial inbound
-- meta_webhook_logs_from_number_idx (WHERE direction='inbound') cobre o lookup real.
drop index if exists public.idx_meta_webhook_logs_from_number;
```

- [ ] **Step 2: Aplicar a migration em prod**

Via MCP: `mcp__supabase-prod__apply_migration` (project_id `tshmvxxxyxgctrdkqvam`, name `meta_webhook_logs_retention`, query = conteúdo do arquivo).
Expected: sucesso; `cron.schedule` retorna o jobid.

- [ ] **Step 3: Verificar agendamento e drop do índice**

Via `mcp__supabase-prod__execute_sql`:
```sql
select jobname, schedule, active from cron.job where jobname = 'purge-meta-webhook-logs';
select indexname from pg_indexes where tablename = 'meta_webhook_logs' order by indexname;
```
Expected: job ativo; `idx_meta_webhook_logs_from_number` ausente; `meta_webhook_logs_from_number_idx` presente.

- [ ] **Step 4: Limpeza inicial dos dados mortos**

Via `mcp__supabase-prod__execute_sql`:
```sql
select public.purge_meta_webhook_logs(15, 10000) as rows_deleted;
```
Expected: ~400k linhas deletadas (tudo anterior a ~12/jun).

- [ ] **Step 5: Reclaim de espaço (justificado)**

A tabela agora tem só o remanescente recente (~dezenas de milhares de linhas). `VACUUM FULL` aqui é justificado e rápido: é log fire-and-forget (escrita concorrente nunca derruba o fluxo — `app/meta_audit.py` engole exceções), o lock exclusivo dura segundos sobre o remanescente pequeno, e é o único caminho para devolver os ~500MB ao disco (DELETE sozinho não reduz o tamanho reportado). Não roda em transação — executar isolado.

Via `mcp__supabase-prod__execute_sql`:
```sql
VACUUM (FULL, ANALYZE) public.meta_webhook_logs;
```

- [ ] **Step 6: Confirmar redução de tamanho**

Via `mcp__supabase-prod__execute_sql`:
```sql
select pg_size_pretty(pg_total_relation_size('public.meta_webhook_logs')) as total,
       (select count(*) from public.meta_webhook_logs) as rows;
```
Expected: total de centenas de MB → poucos MB; DB total bem abaixo de 500 MB.

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/20260627_meta_webhook_logs_retention.sql
git commit -m "feat(db): retencao de 15d via pg_cron + drop de indice redundante em meta_webhook_logs"
```

---

### Task 3: Util `debounce` (TDD) para os hooks de dashboard

**Files:**
- Create: `frontend/src/lib/debounce.ts`
- Test: `frontend/src/lib/debounce.test.ts`

**Interfaces:**
- Produces: `debounce<T extends (...args: any[]) => void>(fn: T, waitMs: number): T & { cancel: () => void }`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/debounce.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { debounce } from "@/lib/debounce";

describe("debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("colapsa múltiplas chamadas em uma só após o intervalo", () => {
    const fn = vi.fn();
    const d = debounce(fn, 1000);
    d(); d(); d();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("cancel() impede a execução pendente", () => {
    const fn = vi.fn();
    const d = debounce(fn, 1000);
    d();
    d.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/debounce.test.ts`
Expected: FAIL — módulo inexistente.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lib/debounce.ts
export function debounce<T extends (...args: any[]) => void>(
  fn: T,
  waitMs: number
): T & { cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const wrapped = ((...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, waitMs);
  }) as T & { cancel: () => void };
  wrapped.cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  return wrapped;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/debounce.test.ts`
Expected: PASS (2 testes)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/debounce.ts frontend/src/lib/debounce.test.ts
git commit -m "feat(frontend): util debounce com cancel (base para cortar refetch dos hooks SLA)"
```

---

### Task 4: Refatorar `use-sla-stats.ts` e `use-overdue-leads.ts` (cortar Egress)

**Files:**
- Modify: `frontend/src/hooks/use-sla-stats.ts`
- Modify: `frontend/src/hooks/use-overdue-leads.ts`

**Interfaces:**
- Consumes: `debounce` de `@/lib/debounce` (Task 3)

- [ ] **Step 1: `use-sla-stats.ts` — colunas explícitas + sem polling + refetch debouncado**

1. Import: adicionar `import { debounce } from "@/lib/debounce";`
2. Trocar `.from("sla_seller_config").select("*")` por colunas explícitas:
```ts
      supabase.from("sla_seller_config").select("user_id, channel_id, display_name, window_start_minute, window_end_minute, active_weekdays, active").eq("active", true),
```
3. No `useEffect`, remover o `setInterval` e debouncar o handler de Realtime:
```ts
  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const debounced = debounce(fetchAndCompute, 1500);
    const channel = supabase
      .channel("sla-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, debounced)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, debounced)
      .subscribe();

    return () => {
      debounced.cancel();
      supabase.removeChannel(channel);
    };
  }, [fetchAndCompute]);
```
(remover a linha `const ticker = setInterval(...)` e o `clearInterval(ticker)`.)

- [ ] **Step 2: `use-overdue-leads.ts` — cutoff temporal + sem polling + refetch debouncado + colunas explícitas**

1. Import: `import { debounce } from "@/lib/debounce";`
2. Trocar `.from("sla_seller_config").select("*")` pelas mesmas colunas explícitas do Step 1.
3. Em `fetchConversations`, adicionar cutoff (overdue só importa para conversas recentes — 30 dias):
```ts
async function fetchConversations(
  supabase: ReturnType<typeof createClient>,
  channelIds: string[]
): Promise<ConvRow[]> {
  if (channelIds.length === 0) return [];
  const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;
  while (true) {
    const { data, error } = await supabase
      .from("conversations")
      .select("id, channel_id, lead_id, last_seller_response_at, leads(name, phone)")
      .in("channel_id", channelIds)
      .gte("created_at", cutoff)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);
    if (error || !data || data.length === 0) break;
    all.push(...(data as unknown as ConvRow[]));
    if (data.length < PAGE) break;
    offset += PAGE;
  }
  return all;
}
```
4. No `useEffect`, remover `setInterval`/`clearInterval` e debouncar o Realtime (mesmo padrão do Step 1, com `.channel("overdue-leads-realtime")`).

- [ ] **Step 3: Verificar typecheck/lint/build**

Run: `cd frontend && npx vitest run src/lib/debounce.test.ts && npm run lint && npx tsc --noEmit`
Expected: testes PASS, lint sem erros novos, typecheck limpo.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/hooks/use-sla-stats.ts frontend/src/hooks/use-overdue-leads.ts
git commit -m "perf(frontend): remove polling 60s, debounca refetch de Realtime, adiciona cutoff 30d e colunas explicitas nos hooks SLA"
```

---

## Self-Review

**Spec coverage:**
- Tratamento de erro no worker (400/404 → cancela; integração retry teto 3) → Task 1 ✓
- Migration/cron de retenção (>15 dias) + limpeza inicial + reclaim → Task 2 ✓
- Drop do índice `idx_meta_webhook_logs_from_number` → Task 2 Step 1/3 ✓
- Hooks: remover setInterval + ajustar refetch + colunas explícitas → Tasks 3+4 ✓
- Cutoff/range em `fetchConversations` → Task 4 Step 2 ✓

**Placeholder scan:** sem TODO/TBD; todo código mostrado por extenso.

**Type consistency:** `decide_failure_update`/`_is_permanent_error` usados em Task 1 batem com as assinaturas declaradas; `debounce` (Task 3) consumido em Task 4 com a mesma assinatura; colunas explícitas batem com as interfaces `SellerConfigRow`/`ConvRow` já existentes.

**Risco conhecido:** `VACUUM FULL` (Task 2 Step 5) — mitigado por purgar antes (remanescente pequeno) e por ser tabela de log fire-and-forget; justificativa documentada inline.

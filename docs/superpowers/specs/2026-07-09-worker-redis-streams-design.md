# Worker orientado a eventos (Redis Streams) + unificação de acesso a dados

**Data:** 2026-07-09
**Status:** aprovado para implementação (P1 + Otimização 3 do relatório de inovação)

## Problema

1. **Falso paralelismo:** `run_worker` (`broadcast/worker.py:739-769`) é um único loop sequencial de 30s que chama 12 funções em série. Uma etapa lenta atrasa todas (um broadcast de 200 leads com sleep 3-8s/lead segura follow-ups por minutos); uma exceção não isolada aborta o tick inteiro; nada escala nem falha de forma independente.
2. **Latência e egress:** disparo/follow-up imediato espera até 30s pelo próximo tick; todas as 12 funções varrem o Supabase a cada 30s mesmo ociosas (o comentário em `worker.py:32-38` reconhece que o polling ocioso domina o egress).
3. **Cliente Supabase síncrono no event loop:** as varreduras e claims chamam `.execute()` direto no loop asyncio (TODO reconhecido em `buffer/processor.py:791`); há 5 políticas de retry independentes.

## Decisão de arquitetura: eventos como *wake-up*, banco como fonte de verdade

Avaliadas duas formas de usar Redis Streams:

- **(a) Fila com estado no evento** (o evento carrega o job; PEL/XAUTOCLAIM como durabilidade) — rejeitada: transfere a fonte de verdade para o Redis, exige reprocessamento idempotente do payload, e duplica os mecanismos de claim atômico que **já existem e funcionam** no banco (`_claim_followup_job`, transição `pending→processing` de broadcast_leads, recovery de stale >5min).
- **(b) Evento como wake-up + varredura como fallback** — **escolhida.** O evento (`XADD`) apenas acorda o domínio; quem decide o que processar continua sendo a varredura no banco (due/pending), com os claims atômicos existentes. Perder um evento custa no máximo um tick de fallback — **nenhum disparo ou follow-up se perde**, porque a linha no banco é a verdade e a varredura a encontra. Crash no meio do processamento é coberto pelos recoveries já existentes (stale claims). Redis fora do ar = degrada exatamente para o comportamento atual (polling).

Sem Celery/arq/mensageria externa; apenas a instância Redis existente (`settings.redis_url`).

## Design

### 1. Barramento de eventos — `app/events/bus.py` (novo)

- `emit_event(domain: str, payload: dict | None = None) -> bool` — **síncrono**, cliente `redis.Redis` module-level lazy (`from_url`, timeouts 2s, `decode_responses=True`), `XADD events:{domain} MAXLEN ~ 1024`. **Fail-open:** qualquer exceção vira `logger.warning` e `return False` — criação de trabalho nunca falha por causa do Redis (o fallback tick cobre).
- Domínios: `broadcasts`, `followups`, `automation`.

**Pontos de emissão** (imediatamente após o INSERT/UPDATE que cria trabalho):

| Domínio | Onde |
|---|---|
| `broadcasts` | `broadcast/router.py` — `start_broadcast`, resume (PATCH status→running) e `create_broadcast` com `scheduled_at` |
| `followups` | `follow_up/service.py` — `schedule_followup`, `schedule_handoff_rescue`, `schedule_ai_return`; `lp_webhook/service.py:332` |
| `automation` | `campaigns/service.py` — insert de `campaign_enrollments` |

### 2. Runtime do worker — `app/worker/runtime.py` + `app/worker/main.py` (novos)

- `run_periodic(name, fn, interval)` — loop isolado: `try: await fn() except: logger.error(exc_info)`, depois `sleep(interval)`. Funções síncronas via `asyncio.to_thread`.
- `run_event_driven(name, fn, domain, fallback_interval)` — cria consumer group (`XGROUP CREATE MKSTREAM`, ignora BUSYGROUP); loop: `XREADGROUP GROUP worker worker-main BLOCK fallback*1000 COUNT 32` → `XACK` imediato (semântica wake-up) → `await fn()`. Timeout do BLOCK = varredura de fallback (chama `fn()` do mesmo jeito). Redis indisponível → log + `sleep(fallback)` + `fn()` (degradação = comportamento atual). `fn()` roda uma vez no startup (recupera o que ficou pendente durante restart).
- `app/worker/main.py` — registro dos domínios e `run_worker()` = `asyncio.gather` de todas as tasks:

| Task | Tipo | Intervalo/Fallback | Funções |
|---|---|---|---|
| `broadcasts` | evento | 60s | `process_scheduled_broadcasts` + `process_broadcasts` |
| `followups` | evento | 30s | `process_due_followups` |
| `automation` | evento | 30s | `check_polling_triggers` + `process_due_enrollments` |
| `llm-parking` | periódico | 30s | `drain_parked_llm_turns` |
| `memory` | periódico | 60s | `process_stale_lead_memories` |
| `channel-health` | periódico | 300s | `check_meta_channel_health` |
| `reconcile` | periódico | 300s | `reconcile_broadcast_replies`, `reconcile_delivery_timeouts`, `retry_undelivered_cold_sends`, `process_wrong_number_deadends` |

- `app/campaign/worker.py` (shim do docker-compose) passa a delegar para `app.worker.main` — **comando do container e docker-compose intocados**.
- O `run_worker` antigo em `broadcast/worker.py` é removido (as funções de domínio ficam).

Ganhos: follow-up/disparo imediato processa em ~segundos (não até 30s); falha num domínio não derruba os outros; reconciliações caem de 120 varreduras/h para 12/h cada (egress).

### 3. Unificação de acesso a dados — `db_call` (Otimização 3, incremental)

Em `app/db/supabase.py`:

```python
async def db_call(fn, *, label: str = "db"):
    """Chamada Supabase síncrona fora do event loop + retry de transporte unificado."""
    return await asyncio.to_thread(run_with_retry, fn, label=label)
```

`asyncio.to_thread` usa o executor default (threads reutilizadas) → o cliente por thread (`threading.local` existente) é reaproveitado, sem criação por chamada.

**Escopo desta fase (hot paths tocados pela P1):**
- Varreduras/claims dos loops de domínio: `process_broadcasts`/`process_scheduled_broadcasts` (queries de tick), `get_due_followups` + claim no `scheduler.py`, varredura de `process_due_enrollments`.
- `buffer/processor.py`: `_save_with_retry` → `db_call` e o site do TODO `:791` (dedup por wamid).

Fora do escopo: converter os ~200 `.execute()` restantes (leads/service etc.) — migração contínua posterior. As 2 políticas de retry substituídas aqui (`_save_with_retry` do processor e chamadas cruas dos loops) convergem para `run_with_retry`; as bordas Meta/LLM mantêm as suas (são específicas de protocolo).

## Testes

- `tests/test_events_bus.py` — emit fail-open (Redis fora → False, sem exceção), XADD no stream certo, MAXLEN.
- `tests/test_worker_runtime.py` — com `fakeredis.aioredis`: (1) evento acorda o domínio antes do fallback; (2) exceção em `fn` não mata o loop; (3) Redis indisponível degrada para tick; (4) `fn` roda no startup; (5) periodic isola exceções.
- Ajuste dos testes existentes que importem `run_worker` de `broadcast/worker` (apontar para `app.worker.main`).
- Suíte inteira verde (`pytest -m "not integration"`) — agora é gate de deploy.

## Riscos

- **Duplo processamento** evento+fallback simultâneos: inócuo — claims atômicos no banco já garantem exclusividade (é o mesmo cenário de dois ticks hoje).
- **Intervalos maiores nas reconciliações** (30s→300s): são varreduras de janelas de minutos/horas (delivery timeout, replies, 72h) — sem impacto funcional.
- **Rollback:** reverter o commit restaura o loop antigo; nenhuma migração de dados, nenhum estado novo obrigatório no Redis.

# P3 — Memória de longo prazo da Valéria: destravar persistência + backfill efetivo

**Data:** 2026-07-09
**Status:** aprovado para implementação

## Problema (estado real após a Onda 2 de 09/07)

A Onda 2 (`3d95648`) já entregou parte do P3: `refresh_lead_memory` ignora o watermark quando não há dossiê prévio (lê histórico completo, cap `MEMORY_BACKFILL_MAX_MSGS=200`) e o script idempotente `backend/scripts/backfill_dossies.py` existe (seleciona `rolling_summary IS NULL`, usa o caminho de produção com lock/fail-soft, `--limit/--sleep/--dry-run`). O modelo já é **flash-lite por default** (`config.py` `memory_model="gemini-2.5-flash-lite"`, env-revertível via `MEMORY_MODEL`). O dossiê é injetado como bloco `<lead_memory>` no **sufixo volátil** do prompt — o prefixo estático cacheável (a7a287e) não é tocado por nada deste trabalho.

Dois bugs impedem o resultado:

1. **Worker pula leads sem dossiê (a via de produção nunca os cura).** `process_stale_lead_memories` usa `_summary_is_current(updated_at, last_msg)` (`memory_manager.py:357`) que só compara watermark — **não checa se `rolling_summary` é NULL**. Vítimas do burn de 08/07 têm watermark avançado com dossiê NULL → são puladas para sempre; conversas curtas novas que caírem na mesma condição idem. O `select` do worker (`:338`) nem busca a coluna `rolling_summary`.
2. **"Histórico completo" na verdade lê 30 mensagens.** `refresh_lead_memory` chama `get_history(lead_id, since=None)` sem `limit` (`memory_manager.py:290`) e o default de `get_history` é `limit=30` (`leads/service.py:1509`). O cap de 200 nunca age; o backfill de leads longos consolida só as 30 primeiras mensagens (ordem asc — as mais antigas).

## Design (mudanças mínimas, 2 arquivos)

### Fix 1 — worker não pula lead sem dossiê (`memory_manager.py`)

- Adicionar `rolling_summary` ao `select` do worker (`:338`).
- No filtro pré-lock (`:357`): pular somente se `_summary_is_current(...)` **e** `lead.get("rolling_summary")` for truthy. Lead com dossiê NULL sempre entra (o `refresh_lead_memory` pós-Onda-2 já sabe reconstituir do histórico completo).

Consequência: conversas curtas passam a persistir dossiê pela via normal do worker (o único guard restante é `if not delta` — delta vazio de verdade), e vítimas de watermark corrompido se autocuram sem depender do script.

### Fix 2 — histórico completo de verdade (`memory_manager.py`)

No caminho sem dossiê prévio: `get_history(lead_id, since=None, limit=MEMORY_BACKFILL_MAX_MSGS)` — o cap de 200 passa a ser real e pega o **fim** do histórico via o slice já existente (`delta[-MEMORY_BACKFILL_MAX_MSGS:]`). Conferir a semântica de `get_history` (ordem asc/desc + limit) para garantir que as 200 retornadas são as MAIS RECENTES; ajustar a query se o limit cortar do lado errado.

### Execução do backfill (operacional, pós-deploy)

`python -m scripts.backfill_dossies --dry-run` primeiro (contagem de candidatos), depois em lotes (`--limit 50`, sleep 2s) **após os fixes estarem em produção** — rodar antes consolidaria dossiês de 30 mensagens. Custo: flash-lite, ~1 chamada por lead, `max_tokens=1024`. Idempotente: reexecuções pulam quem já tem dossiê.

## Testes

- Novo teste: `process_stale_lead_memories` NÃO pula lead com `rolling_summary` NULL e watermark avançado (o cenário exato do burn); continua pulando lead COM dossiê e watermark atual (comportamento do teste existente `test_memory_manager.py:381` preservado com o novo critério).
- Novo teste: caminho sem dossiê passa `limit=MEMORY_BACKFILL_MAX_MSGS` ao `get_history` e consolida as mensagens mais recentes quando o histórico excede o cap.
- Suíte existente de `memory_manager`/`onda2_dossie_backfill` permanece verde.

## Fora de escopo (YAGNI)

Mudar formato/prompt do dossiê, mover o dossiê para o prefixo cacheável (é volátil por design), segundo gatilho de refresh, mudanças no daily QA.

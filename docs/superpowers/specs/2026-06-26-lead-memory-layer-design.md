# Lead Memory Layer — "Dossiê do Lead" (Memória de Longo Prazo)

**Data:** 2026-06-26
**Feature:** Roadmap de Autonomia #1 — Camada de Memória de Longo Prazo
**Status:** Design aprovado (decisões confirmadas pelo usuário)

---

## 1. Problema

Hoje a Valéria sofre de **amnésia cross-canal e limitação de janela de contexto**:

- A memória de trabalho é só a janela por-conversa: `get_history(conversation_id, limit=60)`
  (`orchestrator.run_agent`). Um mesmo lead pode ter **N conversas** (1 por canal Meta —
  ver `[[project_conversa_fragmentada_multicanal]]`), então o que o lead disse num canal
  não chega ao prompt quando ele responde por outro.
- O **único artefato de memória estruturada** é `generate_qualification_summary()`
  (`app/agent/summary.py`), gerado **uma vez**, no handoff (`encaminhar_humano`), e voltado
  para o **João** (briefing de passagem). Não existe memória **viva** que a Valéria leia a
  cada turno.
- Acima de ~60 mensagens, o histórico mais antigo simplesmente some do contexto.

**Objetivo:** dar à Valéria um **Dossiê do Lead** permanente, consolidado e cross-canal, de
forma que ela "acorde" sabendo o histórico completo do cliente — perfil, preferências de
produto, objeções levantadas e estágio do negócio — independentemente de canal ou do tamanho
da janela.

---

## 2. Estado atual (grounding)

| Peça | Onde | Papel hoje |
|---|---|---|
| Janela de conversa | `orchestrator.run_agent` → `conversations.service.get_history(conversation_id, 60)` | Memória de trabalho por-canal |
| Histórico cross-canal | `leads.service.get_history(lead_id, limit)` | **Já lê TODAS as mensagens do lead** (por `lead_id`, não por conversa) — base natural do dossiê |
| Resumo de qualificação | `app/agent/summary.py` → `generate_qualification_summary()` | Briefing congelado p/ o João, gerado no handoff |
| Persistência do resumo | `leads.metadata.handoff_summary` (jsonb) + tabela `lead_notes` | Lido de volta como "LEAD RETORNANDO" |
| Canal de injeção | `processor.py`: `lead_context = lead.get("metadata")` → `base.build_base_prompt` → bloco `<crm_data>` | Hoje injeta `handoff_summary`, `previous_stage`, `notes`, `lead_region`, `lead_is_customer` |
| Loop periódico | `broadcast/worker.py` → `run_worker()` (a cada 5s) | Já roda follow-ups, automation, health checks |
| Sinal de inatividade | `leads.last_customer_message_at` (GLOBAL, cross-canal) — carimbado em `processor.py` e `meta_router.py` em todo inbound | ⚠️ NÃO confundir com `conversations.last_customer_message_at` (POR CANAL, fonte da janela 24h). O worker de memória usa o GLOBAL |

**Conclusões que guiam o design:**
1. A entidade cross-canal já é o `leads` (1 lead = N conversas) → a memória mora na linha do lead.
2. `leads.service.get_history(lead_id)` já consolida todos os canais → fonte do resumo.
3. O canal de injeção (`lead_context` → `<crm_data>`) já existe → basta acrescentar uma chave.
4. Há um loop periódico vivo (`run_worker`, 5s) → o worker de memória pega carona, sem infra nova.

---

## 3. Decisões de arquitetura (confirmadas)

| # | Decisão | Escolha |
|---|---|---|
| D1 | Onde persistir | **Colunas dedicadas** em `leads` (não metadata jsonb) |
| D2 | Estratégia de gatilho | **Worker debounced (inatividade) + hook no `mudar_stage`** |
| D3 | Relação com `handoff_summary` | **Manter os dois separados** (briefing do João ≠ memória viva da Valéria) |
| D4 | Histórico enviado ao LLM | **Apenas o DELTA** (`created_at > rolling_summary_updated_at`) + `prior_summary` |
| D5 | Concorrência | **Lock no banco** (coluna `rolling_summary_processing_at`, claim atômico + TTL) |
| D6 | Formato de saída do LLM | **Structured output (JSON)** → renderizado p/ markdown determinístico |

### Revisão de arquitetura (blockers resolvidos nesta versão)

Uma revisão apontou três blockers de concorrência/custo, todos incorporados abaixo:

- **B1 — Explosão de contexto/custo:** re-resumir o transcript inteiro a cada refresh é
  caro e redundante (o `prior_summary` já codifica os turnos antigos). → **D4**: enviar só o
  delta de mensagens novas.
- **B2 — Worker overlap:** `run_worker` tica a cada 5s, mas o refresh LLM pode levar >5s →
  ticks sobrepostos pegariam o mesmo lead = trabalho duplicado + lost-update no
  `rolling_summary`. → **D5**: lock no banco com claim atômico.
- **B3 — Corrida Gatilho A × Gatilho B:** mesma raiz; centralizar o lock dentro de
  `refresh_lead_memory` faz o Gatilho B falhar em silêncio (fail-soft) quando o A está
  gerando.

---

## 4. Arquitetura proposta

### 4.1 Persistência (D1, D5) — migration aditiva

Três colunas novas em `leads`:

```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary_updated_at timestamptz;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary_processing_at timestamptz;
```

- `rolling_summary` — o dossiê consolidado e evolutivo (texto markdown estruturado).
- `rolling_summary_updated_at` — timestamp da última geração; usado para **debounce**, para o
  cálculo do **delta** (`created_at > rolling_summary_updated_at`) e para detectar "há
  mensagens novas desde o último resumo".
- `rolling_summary_processing_at` — **lock** (D5). `NULL` = livre; setado para `now()` ao
  reivindicar. Recuperação de lock travado (worker que crashou no meio): um lock com
  `processing_at < now() - LOCK_TTL` (≈ 5 min) é considerado livre e pode ser re-reivindicado.

**Por que colunas e não `metadata` jsonb:** escrita atômica de uma coluna evita a corrida de
read-modify-write do jsonb (o orchestrator já faz `update_lead(metadata=...)` para
`previous_stage` — dois escritores no mesmo blob competem). Colunas também são consultáveis
(ex.: "leads com memória stale"). Migration é puramente aditiva.

> **Nota de paridade de ambiente:** aplicar a migration em **prod** (`tshmvxxxyxgctrdkqvam`)
> e **homolog** (`mosbwmsqfcwqdypucgtc`). Após DDL via SQL/MCP, rodar
> `NOTIFY pgrst, 'reload schema'` senão o supabase-py dá `PGRST205` até o cache recarregar
> (ver `[[feedback_postgrest_schema_cache_reload]]`). O `.env.local` aponta p/ homolog.

### 4.2 `memory_manager.py` (novo) — o motor do resumo rolante

Módulo novo: `backend/app/agent/memory_manager.py`. Constantes:
`INACTIVITY_GAP=10min`, `RECENCY_WINDOW=24h`, `LOCK_TTL=5min`, `BATCH_LIMIT=20`.

**Delta de histórico (D4) — alteração em `leads.service.get_history`:**
```python
def get_history(lead_id, limit=30, since: str | None = None) -> list[dict]:
    # ... + (".gt('created_at', since)" quando since is not None)
```
Assim o `memory_manager` busca **apenas** as mensagens com `created_at > rolling_summary_updated_at`.

**Função pura de prompt (unit-testável sem LLM):**
```python
def build_memory_messages(prior_summary: str, delta: list[dict]) -> list[dict]:
    """system+user para gerar o dossiê. O user contém o prior_summary e SÓ o delta."""

def render_dossier(fields: dict) -> str:
    """Renderiza os 5 campos do JSON no markdown fixo do ## DOSSIÊ DO LEAD (determinístico)."""
```

**Função de geração (LLM, structured output — D6, injeção de client p/ teste):**
```python
async def generate_rolling_summary(
    prior_summary: str, delta: list[dict], client: AsyncOpenAI, model: str,
) -> str:
    """Pede JSON estrito (5 campos) via response_format={"type":"json_object"}, parseia e
    renderiza p/ markdown. Fail-soft: erro de LLM, JSON inválido ou delta vazio → devolve o
    `prior_summary` intacto (nunca perde memória, nunca degrada formatação)."""
```

JSON schema (5 chaves string): `perfil_empresa`, `interesse_preferencias`, `objecoes`,
`estagio_negocio`, `proximo_passo`. Structured output elimina "conversinha" ("Aqui está o
dossiê:") e garante formatação estável ao longo do tempo. `reasoning_effort="none"` +
`max_tokens` folgado nos modelos gemini-2.5 (ver `[[feedback_gemini_thinking_tokens]]`).

**Orquestrador de refresh com LOCK (D5, efeitos colaterais isolados):**
```python
async def refresh_lead_memory(lead_id: str, client=None, model=DEFAULT_MODEL) -> bool:
    # 1) CLAIM atômico do lock (UPDATE ... WHERE id=? AND (processing_at IS NULL
    #    OR processing_at < now()-LOCK_TTL)). data vazio → não conseguiu o lock → return False.
    # 2) try:
    #      re-lê o lead (rolling_summary + rolling_summary_updated_at frescos)
    #      delta = leads.get_history(lead_id, since=rolling_summary_updated_at)
    #      if not delta: return False           # nada novo → no-op
    #      new = await generate_rolling_summary(prior, delta, client, model)
    #      if new == prior: return False        # fail-soft não regrediu nada
    #      update_lead(rolling_summary=new, rolling_summary_updated_at=now)
    #      return True
    #    finally:
    #      RELEASE do lock (processing_at = NULL)   # sempre libera, mesmo em erro
```

O **claim atômico** é uma única `UPDATE` com filtro: o Postgres serializa a linha, então de
dois claims concorrentes exatamente um casa a cláusula `WHERE` (o segundo vê `processing_at`
já setado e casa 0 linhas → `data` vazio). Resolve B2 e B3: o Gatilho B, se o A estiver
processando, não consegue o lock e retorna `False` em silêncio.

**Regra dura no prompt:** *"Você recebe o dossiê ANTERIOR e SÓ as mensagens NOVAS. Produza o
dossiê ATUALIZADO. NUNCA descarte um fato já conhecido a menos que as mensagens novas o
contradigam explicitamente. Em conflito, o dado mais recente vence."* — garante acumulação
sem perda mesmo recebendo apenas o delta.

**Cross-canal:** `refresh_lead_memory` lê por `lead_id` (`leads.service.get_history`), portanto
consolida todos os canais por construção.

### 4.3 Gatilhos (D2)

**Gatilho A — Worker debounced por inatividade** (cobre "fim de sessão" e "fechamento da
janela de 24h" sem custo por turno):

Nova função `process_stale_lead_memories(now=None)` em `memory_manager.py`, chamada dentro de
`run_worker()` (`broadcast/worker.py`), logo após `process_due_followups()`.

Seleção (depende de `leads.last_customer_message_at` — campo **global** do lead, carimbado em
TODO inbound por `processor.py` e `meta_router.py`; é o sinal cross-canal correto):
- **janela de recência** (evita backfill da base fria): `last_customer_message_at` ENTRE
  `now - RECENCY_WINDOW` (24h) e `now - INACTIVITY_GAP` (10 min) — ou seja, uma sessão que
  **terminou recentemente**, não leads antigos quaisquer; **E**
- lock livre: `rolling_summary_processing_at IS NULL OR < now - LOCK_TTL`.

> **Comparação coluna-a-coluna** (`rolling_summary_updated_at < last_customer_message_at`) o
> PostgREST não suporta em filtro. Solução sem RPC: a query traz os candidatos (com a janela
> de recência acima, conjunto pequeno) ordenados por `last_customer_message_at ASC` com LIMIT
> defensivo, e o **delta vazio vira no-op dentro de `refresh_lead_memory`** (passo 2: `if not
> delta: return False`). Ou seja, mesmo que um candidato já esteja resumido, ele é descartado
> sem custo de LLM. A janela de recência é o que impede o LLM de varrer a base histórica.

Como o worker roda a cada 5s mas a janela exige inatividade e o lock + delta barram repetição,
o LLM é chamado **uma vez** por "sessão encerrada" de cada lead — não a cada tick. `BATCH_LIMIT`
(≈ 20) por tick limita o custo numa rajada.

**Gatilho B — Hook síncrono no `mudar_stage`** (mudança de segmento é alto sinal):

No `orchestrator.run_agent`, no ponto onde `mudar_stage` já atualiza estado (linha ~603-623),
agendar um refresh **fire-and-forget** (`asyncio.create_task(refresh_lead_memory(lead_id))`)
para não adicionar latência ao turno. Fail-soft: erro no task nunca afeta a resposta ao lead.

> Handoff **não** é um gatilho novo: `encaminhar_humano` continua gerando o `handoff_summary`
> (briefing do João) como hoje (D3). O Gatilho A naturalmente atualiza o `rolling_summary`
> logo depois, quando a conversa esfria.

### 4.4 Injeção no prompt

1. **`processor.py`** (e demais montadores de `lead_context`): acrescentar
   `lead_context["rolling_summary"] = lead.get("rolling_summary")`. (Como hoje o `lead_context`
   parte de `lead.get("metadata")`, o `rolling_summary` — sendo coluna, não metadata — precisa
   ser injetado explicitamente.)
2. **`base.build_base_prompt`**: renderizar um bloco **`<lead_memory>`** distinto do
   `<crm_data>`, posicionado de forma proeminente, com a diretriz:
   *"Esta é sua memória de longo prazo consolidada deste lead (todos os canais). Trate como
   verdade de base, MAS confirme especificidades de forma natural antes de assumir (regra 21,
   anti-premissa). Não recite o dossiê ao lead."*

O `handoff_summary` segue no `<crm_data>` como "LEAD RETORNANDO" (inalterado).

---

## 5. Testes

Unit tests (client LLM fake/injetado, supabase fake; sem rede):

1. **Acúmulo sem perda:** `prior_summary` com fatos A e B + delta com fato C → o prompt
   enviado contém A, B e o delta; o merge (LLM fake) preserva A e B e adiciona C.
2. **Dossiê anterior vazio:** primeira geração funciona com `prior_summary=""`.
3. **Delta-only (D4):** `build_memory_messages` inclui SÓ o delta recebido (não o histórico
   completo); `get_history(lead_id, since=...)` aplica o filtro `created_at > since`.
4. **Structured output (D6):** JSON válido → `render_dossier` produz o markdown fixo dos 5
   campos sem preâmbulo; JSON inválido/com "conversinha" → fail-soft devolve `prior_summary`.
5. **Fail-soft em erro de LLM:** `generate_rolling_summary` devolve `prior_summary`;
   `refresh_lead_memory` não levanta.
6. **No-op sem delta:** `refresh_lead_memory` retorna False e NÃO chama o LLM quando não há
   mensagens novas desde `rolling_summary_updated_at`.
7. **Lock — claim/release (D5):** com o lock livre, `refresh_lead_memory` reivindica e
   **libera no finally** (inclusive em exceção). Com o lock tomado (claim retorna data vazio),
   retorna False sem chamar o LLM (cobre B2 e a corrida Gatilho A×B / B3).
8. **Seleção do worker:** `process_stale_lead_memories` seleciona leads dentro da janela de
   recência (quietos ≥10min, ≤24h) e ignora ativos/antigos; respeita `BATCH_LIMIT`.
9. **Injeção:** `build_base_prompt` com `lead_context={"rolling_summary": "..."}` emite o
   bloco `<lead_memory>`; sem a chave, não emite.

Rodar a suíte existente (`backend/tests`) para garantir ausência de regressão em
`base.build_base_prompt` e `run_agent`.

---

## 6. Escopo / YAGNI

**Dentro do escopo:**
- Colunas `rolling_summary` / `rolling_summary_updated_at`.
- `memory_manager.py` (geração + refresh + worker pass).
- Hook no `mudar_stage`.
- Injeção `<lead_memory>`.
- Testes unitários.

**Fora do escopo (fases futuras do roadmap):**
- RAG / embeddings / pgvector / busca semântica (Fase 2 da Camada de Memória).
- Tools de percepção (CNPJ, frete, PDF) — Feature 2 do roadmap.
- Planejador de cadência multi-touch — Feature 3.
- Autonomia comercial (desconto por volume) — Feature 4.
- Backfill em massa do `rolling_summary` para a base histórica (pode ser script à parte depois).

---

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Gemini gasta budget "pensando" e devolve vazio (ver `[[feedback_gemini_thinking_tokens]]`) | `generate_rolling_summary` usa `max_tokens` folgado + `reasoning_effort="none"` no padrão pós-tool; fail-soft devolve `prior_summary` |
| PGRST205 após DDL | `NOTIFY pgrst, 'reload schema'` nas duas instâncias |
| Custo de LLM por refresh | Debounce por inatividade + delta + LIMIT por tick → ~1 chamada por sessão encerrada |
| Latência no turno | Gatilho B é `asyncio.create_task` (fire-and-forget); Gatilho A roda fora do caminho do turno |
| Perda de memória num merge ruim | Regra dura "nunca descartar fato salvo se contradito"; fail-soft preserva o anterior |
| Corrida de escrita / worker overlap (B2/B3) | Lock no banco (`rolling_summary_processing_at`) com claim atômico + TTL; release no `finally` |
| Lock travado por worker que crashou | TTL de 5 min: lock mais velho que `now-LOCK_TTL` é re-reivindicável |
| Custo/contexto por re-resumo total (B1) | Delta-only: só `created_at > rolling_summary_updated_at` vai ao LLM |
| Backfill acidental da base fria | Janela de recência (24h) na seleção do worker exclui leads antigos |
| Formatação degradando ao longo do tempo | Structured output (JSON) + render determinístico; sem preâmbulo do LLM |

---

## 8. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| Migration SQL (prod + homolog) | `+ rolling_summary`, `+ rolling_summary_updated_at`, `+ rolling_summary_processing_at` |
| `backend/app/agent/memory_manager.py` | **novo** — geração (structured), refresh c/ lock, worker pass |
| `backend/app/leads/service.py` | `get_history` ganha param `since` (delta) |
| `backend/app/agent/prompts/base.py` | renderizar bloco `<lead_memory>` |
| `backend/app/buffer/processor.py` | injetar `rolling_summary` no `lead_context` |
| `backend/app/agent/orchestrator.py` | hook fire-and-forget no `mudar_stage` |
| `backend/app/broadcast/worker.py` | chamar `process_stale_lead_memories()` no loop |
| `backend/tests/test_memory_manager_*.py` | **novo** — testes unitários |

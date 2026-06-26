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

---

## 4. Arquitetura proposta

### 4.1 Persistência (D1) — migration aditiva

Duas colunas novas em `leads`:

```sql
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS rolling_summary_updated_at timestamptz;
```

- `rolling_summary` — o dossiê consolidado e evolutivo (texto markdown estruturado).
- `rolling_summary_updated_at` — timestamp da última geração; usado para **debounce** e para
  detectar "há mensagens novas desde o último resumo".

**Por que colunas e não `metadata` jsonb:** escrita atômica de uma coluna evita a corrida de
read-modify-write do jsonb (o orchestrator já faz `update_lead(metadata=...)` para
`previous_stage` — dois escritores no mesmo blob competem). Colunas também são consultáveis
(ex.: "leads com memória stale"). Migration é puramente aditiva.

> **Nota de paridade de ambiente:** aplicar a migration em **prod** (`tshmvxxxyxgctrdkqvam`)
> e **homolog** (`mosbwmsqfcwqdypucgtc`). Após DDL via SQL/MCP, rodar
> `NOTIFY pgrst, 'reload schema'` senão o supabase-py dá `PGRST205` até o cache recarregar
> (ver `[[feedback_postgrest_schema_cache_reload]]`). O `.env.local` aponta p/ homolog.

### 4.2 `memory_manager.py` (novo) — o motor do resumo rolante

Módulo novo: `backend/app/agent/memory_manager.py`.

**Função pura de prompt (unit-testável sem LLM):**
```python
def build_memory_messages(prior_summary: str, history: list[dict]) -> list[dict]:
    """Monta as mensagens (system+user) para o LLM gerar o dossiê atualizado."""
```

**Função de geração (LLM, injeção de client p/ teste):**
```python
async def generate_rolling_summary(
    prior_summary: str,
    history: list[dict],
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Gera o dossiê atualizado a partir de (dossiê anterior + mensagens). Fail-soft:
    em erro/vazio devolve o `prior_summary` (nunca perde memória existente)."""
```

**Orquestrador de refresh (efeitos colaterais isolados):**
```python
async def refresh_lead_memory(lead_id: str, client=None, model=DEFAULT_MODEL) -> bool:
    """Lê rolling_summary atual + histórico cross-canal (leads.service.get_history(lead_id)),
    gera o dossiê atualizado e grava rolling_summary + rolling_summary_updated_at.
    Idempotente e fail-soft: nunca levanta para o chamador. Retorna True só quando gravou."""
```

**Template fixo do dossiê** (o prompt exige preservar todos os campos; nunca inventar):

```
## DOSSIÊ DO LEAD
* **Perfil / Empresa:** [quem é, segmento, porte; "Não informado" se ausente]
* **Interesse e preferências de produto:** [o que quer, variações, volumes citados]
* **Objeções levantadas:** [preço, frete, prazo, confiança — e se foram resolvidas]
* **Estágio do negócio:** [onde está no funil; sinais de aquecimento]
* **Próximo passo sugerido:** [a melhor próxima ação comercial]
```

**Regra dura no prompt do `memory_manager`:** *"Você recebe o dossiê ANTERIOR e mensagens
NOVAS. Produza o dossiê ATUALIZADO. NUNCA descarte um fato já conhecido a menos que as
mensagens novas o contradigam explicitamente. Em caso de conflito, o dado mais recente vence
e registre a mudança."* — é isto que garante acumulação sem perda.

**Cross-canal:** `refresh_lead_memory` lê por `lead_id` (`leads.service.get_history`), portanto
consolida todos os canais por construção.

### 4.3 Gatilhos (D2)

**Gatilho A — Worker debounced por inatividade** (cobre "fim de sessão" e "fechamento da
janela de 24h" sem custo por turno):

Nova função `process_stale_lead_memories(now=None)` em `memory_manager.py`, chamada dentro de
`run_worker()` (`broadcast/worker.py`), logo após `process_due_followups()`.

Critério de seleção (um lead precisa de refresh quando):
- tem atividade recente do cliente: `last_customer_message_at IS NOT NULL`; **E**
- ficou quieto: `last_customer_message_at < now - INACTIVITY_GAP` (≈ 10 min); **E**
- há mensagens novas desde o último resumo:
  `rolling_summary_updated_at IS NULL OR rolling_summary_updated_at < last_customer_message_at`.

Como o worker roda a cada 5s mas o filtro exige inatividade + delta, o LLM só é chamado **uma
vez** por "sessão encerrada" de cada lead — não a cada tick. Processa em lote pequeno (LIMIT
defensivo, ex. 20 por tick) para não estourar custo numa rajada.

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

Unit tests para `memory_manager` (client LLM fake/injetado, sem rede):

1. **Acúmulo sem perda:** dado um `prior_summary` com fatos A e B + mensagens novas com fato C,
   o prompt enviado contém A, B e o histórico novo; o merge resultante (LLM fake ecoando)
   preserva A e B e adiciona C.
2. **Dossiê anterior vazio:** primeira geração funciona com `prior_summary=""`.
3. **Fail-soft em erro de LLM:** `generate_rolling_summary` devolve o `prior_summary` (não
   perde memória) e `refresh_lead_memory` não levanta.
4. **No-op sem mensagens novas:** `process_stale_lead_memories` não chama o LLM quando
   `rolling_summary_updated_at >= last_customer_message_at`.
5. **Seleção do worker:** o filtro de inatividade + delta seleciona o lead certo e ignora
   leads ativos/recém-resumidos (testar a query/predicado de seleção).
6. **Injeção:** `build_base_prompt` com `lead_context={"rolling_summary": "..."}` emite o
   bloco `<lead_memory>`; sem a chave, não emite o bloco.

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
| Corrida de escrita | Coluna dedicada com UPDATE atômico (não RMW do jsonb) |

---

## 8. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| Migration SQL (prod + homolog) | `+ rolling_summary`, `+ rolling_summary_updated_at` |
| `backend/app/agent/memory_manager.py` | **novo** — geração, refresh, worker pass |
| `backend/app/agent/prompts/base.py` | renderizar bloco `<lead_memory>` |
| `backend/app/buffer/processor.py` | injetar `rolling_summary` no `lead_context` |
| `backend/app/agent/orchestrator.py` | hook fire-and-forget no `mudar_stage` |
| `backend/app/broadcast/worker.py` | chamar `process_stale_lead_memories()` no loop |
| `backend/tests/test_memory_manager_*.py` | **novo** — testes unitários |

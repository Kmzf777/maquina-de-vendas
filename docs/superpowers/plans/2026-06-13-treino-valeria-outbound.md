# Treino da Valéria Outbound (data-driven) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refinar os prompts da Valéria **Outbound** para que, a partir da mensagem de abertura fixa, ela valide interesse, crie rapport, qualifique o lead e encaminhe os qualificados ao vendedor **João** — com tom, quebra de objeção e gatilhos ancorados em conversas inbound reais bem-sucedidas.

**Architecture:** A Valéria outbound nunca rodou, então não há dados outbound. Mineramos as conversas **inbound qualificadas** (única base real) para extrair padrões *transferíveis* (tom, objeções, gatilhos) e os aplicamos ao fluxo **turno-2-em-diante** dos prompts outbound — já que a 1ª mensagem é um template WhatsApp fixo. Editamos **apenas** `backend/app/agent/prompts/valeria_outbound/*`; nunca `base.py`.

**Tech Stack:** Python/FastAPI, Supabase (`supabase-py`, leitura via `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`), pytest. Prompts são strings Python em `PROMPT_REGISTRY` (`backend/app/agent/prompts/__init__.py`).

---

## Contexto

- **Sem dados outbound:** outbound nunca foi disparado. Fonte de dados = conversas **inbound** qualificadas (`leads.status='converted'` + `metadata.handoff_summary` presente / `lead_notes.author='qualificação-ia'`).
- **Mensagem de abertura é FIXA** (template WhatsApp, `{{1}}`=nome). A Valéria-LLM **não escreve o 1º turno** — ela assume a partir da *resposta* do lead:
  > "Olá, tudo bem? Aqui é a Valéria, da Café Canastra. Estamos atualizando nossos registros de contato e queria confirmar rapidinho com você. Falo com {{1}} neste número?"
- **Superfície de design = turno 2+:** confirmar identidade → pivô de "atualizando cadastro" para valor → validar interesse → rapport → qualificar → handoff para **João**.
- **O que os dados sustentam:** tom que ressoa com o público (café Canastra), rebatidas de objeção (preço, "fornecedor atual", "vou pensar"), enquadramento de produto, gatilhos que geraram resposta/avanço.
- **O que NÃO inventamos (anti-alucinação):** personas novas ou a "abertura fria perfeita". A abertura está dada; refinamos o pivô e o tom com base em evidência.
- **Decisões do usuário:** heurística = Qualificado+handoff; escopo = só `valeria_outbound/*` (não tocar `base.py`); extração = script Python local descartável.

## File Structure

| Ação | Caminho | Responsabilidade |
|---|---|---|
| Criar→**apagar** | `backend/scripts/_tmp_extract_conversas.py` | Script descartável de extração read-only |
| Criar→**apagar** | `backend/_tmp_conversas.jsonl` | Saída anonimizada (gitignored) |
| Modificar | `backend/app/agent/prompts/valeria_outbound/secretaria.py` | Entrada: tratar resposta ao template, confirmar identidade, pivô, validar interesse |
| Modificar | `backend/app/agent/prompts/valeria_outbound/atacado.py` | Stage com mais objeção: aplicar rebatidas |
| Modificar (se dados sustentarem) | `valeria_outbound/{private_label,consumo,exportacao}.py` | Tom/gatilho por stage |
| Modificar | `backend/app/agent/prompts/valeria_outbound/context.py` | Enquadrar o template fixo no 1º turno |
| Modificar | `backend/tests/test_base_prompt.py` | Asserções de invariantes outbound (NÃO criar arquivo novo) |
| NÃO tocar | `backend/app/agent/prompts/base.py` | Compartilhado com inbound |

---

## Task 0: Validar conexão, schema e volume (read-only, sem commit)

**Files:** nenhum (só leitura/MCP).

- [ ] **Step 1:** Confirmar que o ambiente local tem `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` apontando para **produção** (checar `backend/.env`). Se NÃO houver cred de prod local → **fallback**: usar `mcp__supabase-prod__execute_sql` (somente SELECT) para os Steps de extração.
- [ ] **Step 2:** Validar schema vivo (read-only): `mcp__supabase-prod__list_tables` e confirmar colunas assumidas: `leads.status`, `leads.metadata`, `leads.ai_enabled`, `lead_notes.author`, `messages.{role,content,created_at,lead_id}`.
- [ ] **Step 3:** Sanity de volume (1 query de contagem):
```sql
SELECT count(*) FROM leads
WHERE status='converted'
  AND (metadata->>'handoff_summary' IS NOT NULL
       OR EXISTS (SELECT 1 FROM lead_notes n WHERE n.lead_id=leads.id AND n.author='qualificação-ia'));
```
Expected: N > 0. Reportar N e a distribuição por `stage`. **Se N for baixo** (ex: < ~15), avisar o usuário no Checkpoint da Task 2 que alguns stages não terão base estatística.

## Task 1: Script de extração descartável (read-only)

**Files:** Create `backend/scripts/_tmp_extract_conversas.py`; Create (saída) `backend/_tmp_conversas.jsonl`; Modify `.gitignore`.

- [ ] **Step 1:** Adicionar ao `.gitignore`:
```
backend/scripts/_tmp_extract_conversas.py
backend/_tmp_conversas*.jsonl
```
- [ ] **Step 2:** Escrever o script (padrão dos scripts existentes em `backend/scripts/`, ex. `diagnose_broadcast_moves.py`). **Somente `.select()` — nenhuma escrita:**
```python
import os, json, re
from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

def mask(text, lead):
    if not text:
        return text
    for field in ("name", "company", "phone"):
        v = (lead.get(field) or "").strip()
        if len(v) >= 4:
            text = text.replace(v, f"[{field.upper()}]")
    text = re.sub(r"\b\d{8,}\b", "[NUM]", text)  # telefones/números longos
    return text

# 1) leads convertidos (qualificados)
leads = sb.table("leads").select(
    "id,phone,name,company,stage,metadata"
).eq("status", "converted").execute().data

# notas de qualificação-ia (fallback de sinal)
notes = sb.table("lead_notes").select("lead_id").eq("author", "qualificação-ia").execute().data
notes_ids = {n["lead_id"] for n in notes}

out = open("backend/_tmp_conversas.jsonl", "w", encoding="utf-8")
n_export = 0
for lead in leads:
    has_summary = bool((lead.get("metadata") or {}).get("handoff_summary"))
    if not (has_summary or lead["id"] in notes_ids):
        continue
    msgs = sb.table("messages").select(
        "role,content,created_at"
    ).eq("lead_id", lead["id"]).in_("role", ["user", "assistant"]).order(
        "created_at"
    ).execute().data
    if not msgs:
        continue
    out.write(json.dumps({
        "lead_id": lead["id"],
        "stage": lead.get("stage"),
        "summary": mask((lead.get("metadata") or {}).get("handoff_summary"), lead),
        "turns": [{"role": m["role"], "content": mask(m["content"], lead)} for m in msgs],
    }, ensure_ascii=False) + "\n")
    n_export += 1
out.close()
print(f"Exportadas {n_export} conversas qualificadas para backend/_tmp_conversas.jsonl")
```
- [ ] **Step 3:** Rodar com env de **produção** (read-only). Run: `python backend/scripts/_tmp_extract_conversas.py`
Expected: imprime "Exportadas N conversas…" e gera `backend/_tmp_conversas.jsonl`.
- [ ] **Step 4:** Conferir o arquivo (contagem de linhas, distribuição por `stage`). Confirmar mascaramento de PII por amostragem. **Sem commit** (artefatos temporários).

## Task 2: Análise, síntese e CHECKPOINT do usuário (sem código)

**Files:** nenhum (análise sobre `backend/_tmp_conversas.jsonl`).

- [ ] **Step 1:** Ler as transcrições e refletir minuciosamente (thinking) sobre a psicologia da venda. Para cada padrão, exigir **evidência + frequência** (só vira "padrão" se aparece em múltiplas conversas):
  - **Objeções:** localizar turns do lead com hesitação/preço/"fornecedor atual"/"vou pensar" e a resposta `assistant` que destravou (seguida de avanço). Registrar trechos reais (anonimizados).
  - **Tom:** formalidade, tamanho de mensagem, emojis, vocabulário regional/café, movimentos de rapport.
  - **Gatilhos:** perguntas, CTAs, enquadramento de produto, prova social, urgência que precederam resposta positiva e avanço de stage.
  - **Caminho de qualificação:** como inbound chegou ao handoff (o que mapeia para o turno-2+ do outbound).
- [ ] **Step 2:** Produzir uma síntese (na conversa, não em arquivo novo) com: padrão → evidência → frequência → **onde entra** (arquivo/seção do outbound) → e se é transferível ou não.
- [ ] **Step 3 — ⛔ PARAR:** Apresentar a síntese ao usuário e **aguardar aprovação explícita** antes de editar qualquer prompt. Também confirmar aqui: **João é o handoff único dos 5 stages, ou exportação mantém o vendedor atual ("Arthur")?** (não assumir).

## Task 3: Refinar `secretaria.py` outbound — resposta ao template + pivô (após aprovação)

**Files:** Modify `backend/app/agent/prompts/valeria_outbound/secretaria.py`; Modify `backend/tests/test_base_prompt.py`.

> A **prosa** vem dos padrões aprovados na Task 2 (anti-alucinação: não pré-escrita aqui). Esta task fixa **onde**, **a estrutura** e os **testes**.

- [ ] **Step 1 (teste primeiro):** Adicionar em `test_base_prompt.py` uma asserção de que o secretaria outbound trata a abertura. Run primeiro para falhar:
```python
def test_outbound_secretaria_trata_abertura_template():
    from app.agent.prompts import get_stage_prompts
    p = get_stage_prompts("valeria_outbound")["secretaria"]
    # seção dedicada a responder o lead após o template "atualizando cadastro / Falo com X?"
    assert "## RESPOSTA À ABERTURA" in p
    assert "cadastro" in p.lower()
```
- [ ] **Step 2:** Run: `pytest backend/tests/test_base_prompt.py::test_outbound_secretaria_trata_abertura_template -v` → Expected: FAIL (seção ainda não existe).
- [ ] **Step 3:** Editar `secretaria.py` (outbound) adicionando a seção `## RESPOSTA À ABERTURA` cobrindo os cenários de resposta ao template (confirma identidade / "quem é?" / "não sou eu" / "sem interesse"), com o **tom/rebatidas aprovados na Task 2**. Preservar o enquadramento de abordagem ativa já existente (ETAPA 0).
- [ ] **Step 4:** Run o teste do Step 2 → Expected: PASS. Rodar também `pytest backend/tests/test_base_prompt.py -v` (não regredir invariantes).
- [ ] **Step 5:** Commit: `git add backend/app/agent/prompts/valeria_outbound/secretaria.py backend/tests/test_base_prompt.py && git commit -m "feat(outbound): secretaria trata abertura fixa e pivota para qualificacao"`

## Task 4: Refinar `atacado.py` outbound — quebra de objeção (após aprovação)

**Files:** Modify `backend/app/agent/prompts/valeria_outbound/atacado.py`.

- [ ] **Step 1:** Para cada objeção recorrente comprovada na Task 2, inserir/ajustar a rebatida na seção correspondente do `atacado.py` outbound, com a **frase/abordagem que funcionou nos dados** (citar evidência no corpo do commit). Não inventar objeções sem lastro.
- [ ] **Step 2:** Run: `pytest backend/tests/test_base_prompt.py -v` → Expected: PASS (invariantes de preço/CSV e produtos removidos do outbound intactos).
- [ ] **Step 3:** Commit: `git add backend/app/agent/prompts/valeria_outbound/atacado.py && git commit -m "feat(outbound): rebatidas de objecao do atacado ancoradas em dados reais"`

## Task 5: Alinhar handoff para João nos prompts outbound (após confirmação na Task 2/Step 3)

**Files:** Modify prompts outbound que citam vendedor; Modify `backend/tests/test_base_prompt.py`.

- [ ] **Step 1 (teste):** Adicionar:
```python
def test_outbound_handoff_para_joao():
    from app.agent.prompts import get_stage_prompts
    full = "\n".join(get_stage_prompts("valeria_outbound").values())
    assert "João" in full
```
- [ ] **Step 2:** Run → Expected: FAIL se nenhum prompt cita João.
- [ ] **Step 3:** Ajustar o nome do vendedor para **João** no caminho de handoff dos stages confirmados (manter exportação/"Arthur" apenas se o usuário confirmou exceção na Task 2).
- [ ] **Step 4:** Run o teste → PASS. Rodar suite completa de prompt.
- [ ] **Step 5:** Commit: `git add -A backend/app/agent/prompts/valeria_outbound backend/tests/test_base_prompt.py && git commit -m "feat(outbound): handoff de leads qualificados para Joao"`

## Task 6: Enquadrar o template fixo em `context.py` (após aprovação)

**Files:** Modify `backend/app/agent/prompts/valeria_outbound/context.py`.

- [ ] **Step 1:** Revisar `build_outbound_first_turn_context()` para deixar explícito que a `campaign_message` recebida É a abertura fixa "atualizando cadastro / Falo com X?", orientando a Valéria a não repetir a apresentação e a já pivotar. Manter assinatura/contrato da função.
- [ ] **Step 2:** Run: `pytest backend/tests/test_base_prompt.py backend/tests/test_agent_summary.py -v` → Expected: PASS.
- [ ] **Step 3:** Commit: `git add backend/app/agent/prompts/valeria_outbound/context.py && git commit -m "feat(outbound): contexto do 1o turno reconhece abertura fixa do template"`

## Task 7: Verificação end-to-end

- [ ] **Step 1:** Run: `pytest backend/tests/test_base_prompt.py backend/tests/test_agent_summary.py -v` → Expected: todos PASS. Colar a saída real.
- [ ] **Step 2:** Revisar manualmente o diff dos prompts (coerência de tom, sem regressão, sem PII vazada).
- [ ] **Step 3 (manual, usuário):** Simular um turno outbound no Dev (VS Code task `Run All Dev (CRM & Backend)`) iniciando pela resposta do lead ao template, validando o pivô e o handoff para João.

## Task 8: Limpeza e entrega

- [ ] **Step 1:** Apagar temporários: `rm backend/scripts/_tmp_extract_conversas.py backend/_tmp_conversas*.jsonl` e confirmar `git status` limpo desses artefatos (regra de contenção).
- [ ] **Step 2:** Confirmar que nenhum arquivo novo de abstração foi criado e que `base.py` não foi tocado.
- [ ] **Step 3 — ⛔ PARAR (regra de ouro do git):** Avisar o usuário que está commitado e **aguardar autorização expressa** para `git push origin master`. NÃO fazer push sozinho (push = deploy de produção).

---

## Anti-alucinação (regra central)

A prosa dos prompts (Tasks 3, 4, 6) **não é pré-escrita neste plano**: ela é derivada dos padrões **aprovados na Task 2**, com evidência citada no corpo de cada commit. Mudanças sem lastro nos dados (ou requisitos diretos do usuário, como o nome João) não entram.

## Self-Review (writing-plans)

- **Cobertura do spec:** Extração (T1) ✓ · Filtro de sucesso (T0/T1, status=converted+handoff_summary) ✓ · Análise/síntese: objeção/tom/gatilhos (T2) ✓ · Refino do prompt outbound existente (T3–T6) ✓ · Progresso incremental com checkpoint (T2/Step3) ✓ · Sem novos arquivos de abstração + apagar script temp (T1/T8) ✓ · Mensagem de abertura fixa + handoff João (contexto/T3/T5/T6) ✓.
- **Placeholders:** prosa de prompt é intencionalmente data-derivada (não placeholder) e marcada como tal; código de script/testes/comandos é concreto.
- **Consistência de tipos:** testes usam `get_stage_prompts("valeria_outbound")[stage]` conforme `__init__.py`/`orchestrator.py` (confirmar assinatura no 1º run do teste).

## Execution Handoff

Após aprovação, escolher: **(1) Subagent-Driven** (subagente por task, revisão entre tasks — recomendado) ou **(2) Inline** (executar nesta sessão com checkpoints). Eu uso a sub-skill correspondente.

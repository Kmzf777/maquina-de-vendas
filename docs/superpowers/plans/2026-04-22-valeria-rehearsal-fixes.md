# Valéria Rehearsal Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir 4 defeitos críticos identificados na bateria de rehearsal `2026-04-22T18-32-06` (loop infinito, amnésia/flapping, crash silencioso no R2, alucinação anti-profissional em B2B private_label) sem quebrar os testes atuais.

**Architecture:** Correções em duas camadas — (1) **Prompt** (base.py + stage prompts) para travar política de preço/frete e amostras; (2) **Código** (orchestrator, tools, rehearsal_runner) para adicionar encerramento explícito, trava de stage, injeção de estado da sessão e instrumentação de crash. Zero novas dependências. Nenhum módulo RAG genérico.

**Tech Stack:** Python 3.12, FastAPI, OpenAI gpt-4.1-mini, pytest + pytest-asyncio, Redis (FakeRedis nos testes), Supabase.

**Decisões do dono da empresa que restringem este plano:**
1. **PRECO_FRETE**: Regex do forbid permanece. Remover "gira em torno de" do prompt. Proibir explicitamente qualquer cálculo/estimativa de frete ou preço total fora das tabelas do RAG. Se cliente pede total com frete → `encaminhar_humano`.
2. **AMOSTRAS**: Nunca proativa. Apenas reativa quando lead trava exigindo degustação. Kit pago (R$60 Sul/SE/CO, R$90 N/NE) como barreira de qualificação. Sem módulo RAG — patch hard-coded em `private_label.py` e `base.py`, atacado também ajustado.
3. **R2 crash**: Criar instrumentação. **NÃO rodar** o teste R2 isolado — o usuário roda depois.

---

## File Structure

### Modified
- `backend/app/agent/prompts/base.py` — Reescrever regra 12 (PRECO E REFERENCIA), adicionar regra sobre amostras em SITUACOES ESPECIAIS.
- `backend/app/agent/prompts/valeria_inbound/atacado.py` — Remover "Quando oferecer" proativo do KITS AMOSTRA, remover "gira em torno de" do exemplo de preços.
- `backend/app/agent/prompts/valeria_inbound/private_label.py` — Adicionar KITS AMOSTRA reativo, adicionar "torra externa" em SITUACOES ADVERSAS.
- `backend/app/agent/tools.py` — Adicionar tool `encerrar_sessao` + schema + incluir em `get_tools_for_stage`.
- `backend/app/agent/orchestrator.py` — Detecção de despedida consecutiva, trava de stage após primeira transição, injeção de bloco `[ESTADO DA SESSÃO]`.
- `backend/scripts/rehearsal_runner.py` — Checkpoints de log, `crash.log` por arquétipo, dump de artefatos parcial em exceção.

### Created
- `backend/tests/agent/test_prompt_policies.py` — Asserts sobre conteúdo dos prompts (regra 12 sem "em torno de", amostras reativas, etc.).
- `backend/tests/agent/test_tools_encerrar_sessao.py` — Schema da tool nova e presença por stage.
- `backend/tests/agent/test_orchestrator_session_controls.py` — Farewell detection, stage lock, bloco de estado.
- `backend/tests/rehearsal/test_runner_instrumentation.py` — Checkpoints e crash.log gerados mesmo em exceção.

---

## Task 1: Instrumentar `rehearsal_runner.py` (P4 — crash silencioso R2)

**Files:**
- Modify: `backend/scripts/rehearsal_runner.py`
- Create: `backend/tests/rehearsal/test_runner_instrumentation.py`

**Objetivo:** Nenhuma execução de arquétipo pode terminar sem deixar rastro. Se `_run_archetype` lança exceção, escrever `crash.log` (tipo, mensagem, traceback, turno atual, histórico parcial) na pasta do arquétipo antes de propagar.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/rehearsal/test_runner_instrumentation.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_archetype_writes_crash_log_on_exception(tmp_path, monkeypatch):
    """Se _run_archetype levanta exceção no meio do loop, deve deixar crash.log."""
    from backend.scripts import rehearsal_runner

    archetype_dir = tmp_path / "R9-boom"
    archetype_dir.mkdir()

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated explosion at turn 3")

    monkeypatch.setattr(rehearsal_runner, "_send_user_message", boom)

    ctx = rehearsal_runner.RunContext(
        run_dir=tmp_path,
        redis_client=AsyncMock(),
        http_client=AsyncMock(),
    )
    archetype = {
        "id": "R9-boom",
        "persona_prompt": "x",
        "lead_phone": "5599999999999",
        "max_turns": 5,
    }

    with pytest.raises(RuntimeError):
        await rehearsal_runner._run_archetype(ctx, archetype, out_dir=archetype_dir)

    crash = archetype_dir / "crash.log"
    assert crash.exists(), "crash.log deve ser gerado quando _run_archetype explode"
    payload = json.loads(crash.read_text())
    assert payload["exception_type"] == "RuntimeError"
    assert "simulated explosion" in payload["message"]
    assert "traceback" in payload
    assert payload["archetype_id"] == "R9-boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/rehearsal/test_runner_instrumentation.py -v`
Expected: FAIL — `crash.log` não existe (comportamento atual: exceção propaga sem artefato).

- [ ] **Step 3: Add instrumentation to `_run_archetype`**

Abrir `backend/scripts/rehearsal_runner.py`. Localizar `async def _run_archetype(...)`. Envolver o corpo principal em `try/except` que captura qualquer `Exception`, escreve `crash.log`, e re-propaga.

```python
# Near top of file, alongside other imports
import traceback

# Inside _run_archetype, right after resolving out_dir
turn_index = 0
partial_history: list[dict] = []
try:
    # ... corpo existente da função ...
    # Onde já se incrementa o turno, adicionar:
    #   turn_index = turn + 1
    # Onde já se acumula histórico do arquétipo, adicionar:
    #   partial_history.append({"role": ..., "content": ...})
    ...
except Exception as exc:
    crash_payload = {
        "archetype_id": archetype.get("id"),
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "turn_index_at_crash": turn_index,
        "partial_history": partial_history,
    }
    (out_dir / "crash.log").write_text(
        json.dumps(crash_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raise
```

Se a função atualmente faz `write_archetype_artifacts` só no final (happy path), mover a parte que grava `history.json` parcial para dentro do `except` também, usando `partial_history`.

Adicionar também logs de checkpoint (`logger.info`) antes de cada IO crítico:
- antes de `wipe_lead`
- antes de `wipe_redis_buffer`
- dentro do loop: `"[runner] %s turn=%d → sending", archetype_id, turn_index`
- após receber resposta do bot: `"[runner] %s turn=%d ← got %d bot messages"`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/rehearsal/test_runner_instrumentation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rehearsal_runner.py backend/tests/rehearsal/test_runner_instrumentation.py
git commit -m "feat(rehearsal): instrument _run_archetype with crash.log + checkpoints"
```

**⚠️ Não rodar `python -m backend.scripts.rehearsal_runner` — usuário executa manualmente depois.**

---

## Task 2: Endurecer base.py — Regra 12 (PRECO_FRETE)

**Files:**
- Modify: `backend/app/agent/prompts/base.py` (regra 12 dentro de REGRAS ABSOLUTAS)
- Create: `backend/tests/agent/test_prompt_policies.py`

**Objetivo:** Eliminar o conflito entre o prompt (que instrui "fica em torno de") e o forbid regex (que trata isso como violação). Prompt passa a proibir explicitamente qualquer estimativa de frete ou preço total fora das tabelas do RAG.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_prompt_policies.py
from backend.app.agent.prompts.base import BASE_PROMPT


def test_rule_12_forbids_estimates_not_in_rag():
    """Regra 12 deve proibir estimativa de frete/total fora da tabela do RAG."""
    # O prompt NÃO deve mais instruir o uso de 'em torno de' / 'por volta de' / 'na faixa de'
    # como template genérico de preço.
    assert "gira em torno de" not in BASE_PROMPT
    assert "fica em torno de" not in BASE_PROMPT
    assert "na faixa de" not in BASE_PROMPT

    # Deve conter a nova trava explícita:
    assert "NUNCA estime frete" in BASE_PROMPT
    assert "encaminhar_humano" in BASE_PROMPT  # already there, but keep safety
    assert "preço total com frete" in BASE_PROMPT or "preco total com frete" in BASE_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_rule_12_forbids_estimates_not_in_rag -v`
Expected: FAIL — string "gira em torno de" ainda presente.

- [ ] **Step 3: Rewrite rule 12 in base.py**

Abrir `backend/app/agent/prompts/base.py`. Localizar a seção iniciada por `12. PRECO E REFERENCIA, NUNCA COMPROMISSO FINAL`. Substituir **todo o bloco da regra 12** por:

```
12. PRECO: FIDELIDADE LITERAL A TABELA, NUNCA ESTIMATIVA
   - Todo preco unitario que voce disser deve vir LITERAL da tabela do funil ativo. Fale o numero direto: "o 250g sai R$23,90". Nao use verbos de aproximacao como "gira em torno de", "fica em torno de", "na faixa de", "por volta de" — eles ja causaram violacao de compliance.
   - NUNCA calcule, some, multiplique ou estime:
     * frete (valor exato ou aproximado)
     * preco total (produto + frete)
     * preco para quantidades fora das ja tabuladas
     * desconto, condicao especial, parcelamento
   - Se o cliente pedir "quanto fica no total com o frete?", "quanto da tudo junto?", "qual o valor final com entrega?", responda: "o valor final com frete quem fecha e nosso comercial — ja vou te passar pra ele" e execute encaminhar_humano imediatamente.
   - Frete voce so pode citar o que esta literal na tabela de FRETE do funil (valor fixo por regiao, pedido minimo, frete gratis acima de X). Nunca invente valor para cidade/CEP especifico.
   - Se a pergunta do cliente exige um numero que nao esta na tabela, a resposta correta e encaminhar_humano — nunca improvisar.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_rule_12_forbids_estimates_not_in_rag -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/base.py backend/tests/agent/test_prompt_policies.py
git commit -m "feat(prompt): harden rule 12 — ban freight/total estimates outside RAG tables"
```

---

## Task 3: Adicionar regra "Amostra nunca proativa" em base.py

**Files:**
- Modify: `backend/app/agent/prompts/base.py` (seção SITUACOES ESPECIAIS)
- Modify: `backend/tests/agent/test_prompt_policies.py`

- [ ] **Step 1: Write the failing test**

Adicionar ao arquivo existente:

```python
def test_base_prompt_bans_proactive_sample_offer():
    from backend.app.agent.prompts.base import BASE_PROMPT
    assert "Amostra NUNCA" in BASE_PROMPT
    assert "Kit" in BASE_PROMPT and "R$60" in BASE_PROMPT
    # Regra deve deixar claro que so aciona se o LEAD pedir primeiro
    assert "so se o lead" in BASE_PROMPT or "somente se o lead" in BASE_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_base_prompt_bans_proactive_sample_offer -v`
Expected: FAIL.

- [ ] **Step 3: Add rule to SITUACOES ESPECIAIS in base.py**

Localizar a seção `## SITUACOES ESPECIAIS` em `backend/app/agent/prompts/base.py`. Adicionar ao final da seção (antes da próxima `##`):

```
### Cliente pede amostra / degustacao
REGRA ABSOLUTA: Amostra NUNCA e ofertada proativamente. Voce esta PROIBIDA de sugerir "quer um kit pra experimentar?", "posso mandar uma degustacao?", "que tal provar antes?". Nem mesmo com rodeios.

So mencione amostra se o proprio lead PEDIR primeiro, travando a negociacao: "preciso provar antes de comprar", "nao fecho sem experimentar", "voces mandam amostra?", "tem como testar o cafe?". So nessa situacao, apresente o Kit Degustacao PAGO como barreira de qualificacao:

- Kit 1 (moido) ou Kit 2 (graos), R$60 com frete incluso para Sul/Sudeste/Centro-Oeste, R$90 para Norte/Nordeste.
- Diga que nao trabalhamos com amostra gratis e que o kit ja vem com frete embutido.
- NUNCA ofereca microlote como amostra (cafe diferente, 86 SCA, nao representa o produto que ele vai revender).

Se o lead aceitar o kit pago, siga o fluxo normal de registrar_pedido_simples + encaminhar_humano.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_base_prompt_bans_proactive_sample_offer -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/base.py backend/tests/agent/test_prompt_policies.py
git commit -m "feat(prompt): ban proactive sample offer — reactive-only paid kit barrier"
```

---

## Task 4: Reescrever `atacado.py` — KITS AMOSTRA reativo + remover "gira em torno"

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/atacado.py`
- Modify: `backend/tests/agent/test_prompt_policies.py`

- [ ] **Step 1: Write the failing tests**

Adicionar:

```python
def test_atacado_kits_is_reactive_only():
    from backend.app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    # Nao pode ter linguagem proativa de oferta
    assert "Quando oferecer" not in ATACADO_PROMPT
    # Deve explicitar trigger reativo (lead trava negociacao)
    assert "Quando o lead exigir" in ATACADO_PROMPT or "so se o lead exigir" in ATACADO_PROMPT

def test_atacado_pricing_example_uses_literal_prices():
    from backend.app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    # O exemplo anterior usava "gira em torno de R$28,70" — conflitava com o forbid regex
    assert "gira em torno de" not in ATACADO_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py -v -k atacado`
Expected: FAIL em ambos.

- [ ] **Step 3: Edit atacado.py**

Abrir `backend/app/agent/prompts/valeria_inbound/atacado.py`.

**Edit A** — Na seção `## KITS AMOSTRA`, substituir o bloco inteiro `### Quando oferecer ... NAO disparar para duvidas sobre relacionamento, preco ou logistica.` por:

```
### Quando oferecer (REATIVO APENAS)
REGRA ABSOLUTA: voce NAO oferece kit amostra proativamente. Nao pergunta se quer experimentar, nao sugere degustacao, nao menciona amostra em nenhuma hipotese.

Gatilho unico: o LEAD trava a negociacao exigindo provar antes de fechar. Frases tipo "preciso provar antes de comprar", "nao fecho sem experimentar", "voces mandam amostra?", "tem como testar o cafe?".

Apenas nessa situacao, apresente o Kit como PAGO (barreira de qualificacao, nao brinde).

Exemplo tipico: "100 unidades e muito pra testar se meu cliente vai gostar"
Resposta correta: oferecer Kit Amostra PAGO (NAO microlote — microlote e cafe diferente, 86 SCA vs 84 SCA, e nao serve como amostra do cafe que ele vai revender)
```

**Edit B** — Na seção `## COMO APRESENTAR PRECOS`, substituir:

```
"o classico moido 250g gira em torno de R$28,70"
"se preferir em graos, R$31,70 no mesmo tamanho"
"temos de 250g ate granel de 2kg"
```

por:

```
"o classico moido 250g sai R$28,70"
"se preferir em graos, R$31,70 no mesmo tamanho"
"temos de 250g ate granel de 2kg"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py -v -k atacado`
Expected: PASS em ambos.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/atacado.py backend/tests/agent/test_prompt_policies.py
git commit -m "feat(prompt/atacado): reactive-only sample kit, literal price phrasing"
```

---

## Task 5: Adicionar KITS AMOSTRA (reativo) em `private_label.py`

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/private_label.py`
- Modify: `backend/tests/agent/test_prompt_policies.py`

**Motivação (R5):** Hoje `private_label.py` não tem seção KITS AMOSTRA. Quando um lead B2B caiu nesse funil e pediu amostra, o LLM improvisou a resposta anti-profissional "conhece alguem que poderia comprar cafe da gente". Precisa da mesma seção reativa.

- [ ] **Step 1: Write the failing test**

```python
def test_private_label_has_reactive_sample_kit():
    from backend.app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "KITS AMOSTRA" in PRIVATE_LABEL_PROMPT
    assert "REATIVO APENAS" in PRIVATE_LABEL_PROMPT
    assert "R$60" in PRIVATE_LABEL_PROMPT and "R$90" in PRIVATE_LABEL_PROMPT
    # Proibicao de improvisar
    assert "conhece alguem" not in PRIVATE_LABEL_PROMPT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_private_label_has_reactive_sample_kit -v`
Expected: FAIL.

- [ ] **Step 3: Insert KITS AMOSTRA section in private_label.py**

Abrir `backend/app/agent/prompts/valeria_inbound/private_label.py`. Inserir **antes** de `## SITUACOES ADVERSAS` (que fica logo antes da ETAPA DE HANDOFF) o bloco abaixo:

```
## KITS AMOSTRA

### Quando oferecer (REATIVO APENAS)
REGRA ABSOLUTA: voce NAO oferece kit amostra proativamente. Nao pergunta se quer experimentar, nao sugere degustacao, nao menciona amostra em nenhuma hipotese. Nunca, jamais, sugira que o lead passe o contato de terceiros ou "conheca alguem que poderia comprar" — isso e anti-profissional e esta PROIBIDO.

Gatilho unico: o LEAD trava a negociacao do private label exigindo provar o cafe base antes de fechar. Frases tipo "preciso provar antes de fechar a marca", "nao encomendo sem experimentar o cafe", "voces mandam amostra do cafe?", "tem como testar a qualidade antes?".

Apenas nessa situacao, apresente o Kit como PAGO (barreira de qualificacao, nao brinde).

### Produtos

**Kit 1 — Moido:**
- Conteudo: 40g Suave + 40g Classico + 40g Canela (moido) + 3 drips
- Preco: R$60 (Sul/Sudeste/Centro-Oeste) ou R$90 (Norte/Nordeste)
- Frete: ja incluso no preco

**Kit 2 — Graos:**
- Conteudo: 100g Suave + 100g Classico (graos) + 40g Canela (moido) + 3 drips
- Preco: R$60 (Sul/Sudeste/Centro-Oeste) ou R$90 (Norte/Nordeste)
- Frete: ja incluso no preco

### Como apresentar

Use Kit 1 se o lead mencionou cafe moido ou nao especificou. Use Kit 2 se o lead mencionou graos.

Apresente como produto PAGO. Destaque que o frete ja esta incluso.

Exemplo de resposta:
"a gente tem um Kit Degustacao pra isso"
"sao tres cafes diferentes — Suave, Classico e Canela — mais alguns drips pra voce testar cada um"
"sai R$60 com frete incluso pra Sao Paulo"
"assim voce prova o cafe base antes de fechar a producao da sua marca"

Depois de apresentar o kit, pergunte qual regiao do cliente (se ainda nao souber) para confirmar o preco correto. Se o lead aceitar, siga o fluxo normal: registrar_pedido_simples + encaminhar_humano.

---

```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_private_label_has_reactive_sample_kit -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/private_label.py backend/tests/agent/test_prompt_policies.py
git commit -m "feat(prompt/private_label): add reactive-only sample kit section (fixes R5 hallucination)"
```

---

## Task 6: Situação adversa "torra externa" em `private_label.py`

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/private_label.py`
- Modify: `backend/tests/agent/test_prompt_policies.py`

**Motivação:** Leads que querem usar grão próprio / torra externa não cabem no funil private_label (que assume grão da Fazenda Pratinha). Precisa de `encaminhar_humano` imediato, não de improviso.

- [ ] **Step 1: Write the failing test**

```python
def test_private_label_handles_external_roast():
    from backend.app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "torra externa" in PRIVATE_LABEL_PROMPT.lower() or "grao proprio" in PRIVATE_LABEL_PROMPT.lower()
    # Deve encaminhar, nao improvisar
    assert PRIVATE_LABEL_PROMPT.lower().count("encaminhar_humano") >= 2  # handoff + torra externa
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_private_label_handles_external_roast -v`
Expected: FAIL.

- [ ] **Step 3: Add situação adversa**

Em `backend/app/agent/prompts/valeria_inbound/private_label.py`, dentro de `## SITUACOES ADVERSAS`, após o bloco "### Cliente quer exportar", acrescentar:

```
### Cliente quer apenas torra / embalagem de grao proprio (externo)
Gatilho: cliente diz que ja tem o cafe/grao e quer apenas o servico de torra, moagem ou embalagem. Palavras-chave: "meu proprio grao", "grao que eu compro", "so a torra", "so embalar", "so o servico de embalagem", "ja tenho o cafe", "quero usar meu cafe".

IMEDIATAMENTE execute encaminhar_humano(vendedor="Joao Bras", motivo="torra externa — grao proprio do cliente") NA MESMA RESPOSTA.
Apos chamar a tool, envie UMA UNICA mensagem: "entendi, voce ja tem o cafe e quer so o servico. isso foge do nosso private label padrao, vou passar pro Joao Bras ajustar uma proposta sob medida pra voce."

REGRA CRITICA: nao improvise preco de torra/embalagem avulsa. Nao invente condicao. A chamada de encaminhar_humano ja finaliza sua participacao.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_prompt_policies.py::test_private_label_handles_external_roast -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/private_label.py backend/tests/agent/test_prompt_policies.py
git commit -m "feat(prompt/private_label): add 'external roast' adverse situation → encaminhar_humano"
```

---

## Task 7: Nova tool `encerrar_sessao` (P1-A)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Create: `backend/tests/agent/test_tools_encerrar_sessao.py`

**Motivação (R3 loop infinito):** Hoje só há 2 formas de sair do loop: `max_turns` (consome tokens) ou `encaminhar_humano` (requer motivo de negócio). Quando o cliente apenas se despede, não há mecanismo de término. Criar tool explícita.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_tools_encerrar_sessao.py
import pytest


def test_encerrar_sessao_schema_is_valid():
    from backend.app.agent.tools import TOOL_SCHEMAS
    schema = next((s for s in TOOL_SCHEMAS if s["function"]["name"] == "encerrar_sessao"), None)
    assert schema is not None, "tool encerrar_sessao precisa estar em TOOL_SCHEMAS"
    params = schema["function"]["parameters"]
    assert "motivo" in params["properties"]
    assert params["required"] == ["motivo"]


def test_encerrar_sessao_available_in_every_stage():
    from backend.app.agent.tools import get_tools_for_stage
    for stage in ["secretaria", "atacado", "private_label", "exportacao", "consumo"]:
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "encerrar_sessao" in names, f"encerrar_sessao deve existir no stage {stage}"


@pytest.mark.asyncio
async def test_encerrar_sessao_handler_marks_session_closed(monkeypatch):
    from backend.app.agent import tools
    calls = []

    async def fake_set_session_closed(conversation_id, motivo):
        calls.append((conversation_id, motivo))

    monkeypatch.setattr(tools, "set_session_closed", fake_set_session_closed, raising=False)
    result = await tools.encerrar_sessao_handler(
        conversation_id="conv-1",
        motivo="cliente se despediu",
    )
    assert result["ok"] is True
    assert calls == [("conv-1", "cliente se despediu")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_tools_encerrar_sessao.py -v`
Expected: FAIL — schema inexistente.

- [ ] **Step 3: Add tool, schema and handler**

Em `backend/app/agent/tools.py`:

**Edit A** — Acrescentar em `TOOL_SCHEMAS`:

```python
{
    "type": "function",
    "function": {
        "name": "encerrar_sessao",
        "description": (
            "Encerra a conversa quando o atendimento esta concluido e o cliente se despediu. "
            "Use quando: cliente disse tchau/obrigado claramente, OU voce ja encaminhou para humano "
            "e o cliente respondeu apenas com confirmacao curta. Nunca use no meio de uma negociacao ativa."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "motivo": {
                    "type": "string",
                    "description": "Motivo do encerramento (ex: 'cliente se despediu', 'pos-handoff').",
                },
            },
            "required": ["motivo"],
        },
    },
},
```

**Edit B** — Acrescentar handler:

```python
async def encerrar_sessao_handler(conversation_id: str, motivo: str) -> dict:
    """Marca a sessao como encerrada para que o orchestrator pare o loop."""
    try:
        await set_session_closed(conversation_id, motivo)
    except NameError:
        # set_session_closed ainda nao importado — adicionar import abaixo
        raise
    return {"ok": True, "motivo": motivo}
```

Adicionar import no topo do arquivo (ou onde os outros handlers importam):

```python
from backend.app.agent.session_state import set_session_closed
```

**Edit C** — Em `get_tools_for_stage`, adicionar `"encerrar_sessao"` à lista de **cada** stage (secretaria, atacado, private_label, exportacao, consumo).

**Edit D** — Criar `backend/app/agent/session_state.py` (ou estender arquivo existente se já houver) com:

```python
from backend.app.redis import get_redis


SESSION_CLOSED_KEY = "session:closed:{conversation_id}"


async def set_session_closed(conversation_id: str, motivo: str) -> None:
    r = await get_redis()
    await r.setex(
        SESSION_CLOSED_KEY.format(conversation_id=conversation_id),
        60 * 60 * 24,  # 24h
        motivo,
    )


async def is_session_closed(conversation_id: str) -> bool:
    r = await get_redis()
    val = await r.get(SESSION_CLOSED_KEY.format(conversation_id=conversation_id))
    return val is not None
```

(Se já existir `session_state.py` com outro propósito, acrescentar as duas funções acima sem duplicar.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_tools_encerrar_sessao.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/session_state.py backend/tests/agent/test_tools_encerrar_sessao.py
git commit -m "feat(agent): add encerrar_sessao tool + session state redis flag"
```

---

## Task 8: Farewell detection no `orchestrator.py` (P1-C)

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Create: `backend/tests/agent/test_orchestrator_session_controls.py`

**Motivação:** Mesmo com a tool nova, o LLM pode não chamá-la. Regex detecta 2 despedidas consecutivas do usuário e força `encerrar_sessao` automaticamente.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agent/test_orchestrator_session_controls.py
import pytest


def test_detect_consecutive_farewells_true_case():
    from backend.app.agent.orchestrator import _detect_consecutive_farewells
    history = [
        {"role": "assistant", "content": "perfeito, ate mais!"},
        {"role": "user", "content": "obrigado, tchau"},
        {"role": "assistant", "content": "tchau!"},
        {"role": "user", "content": "valeu, boa tarde"},
    ]
    assert _detect_consecutive_farewells(history, threshold=2) is True


def test_detect_consecutive_farewells_false_case():
    from backend.app.agent.orchestrator import _detect_consecutive_farewells
    history = [
        {"role": "user", "content": "me manda o preco"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "obrigado"},
    ]
    assert _detect_consecutive_farewells(history, threshold=2) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_orchestrator_session_controls.py -v`
Expected: FAIL — função inexistente.

- [ ] **Step 3: Add detector in orchestrator.py**

Abrir `backend/app/agent/orchestrator.py`. Adicionar no topo (após imports):

```python
import re

_FAREWELL_RE = re.compile(
    r"\b(tchau|ate\s+mais|ate\s+logo|ate\s+(amanha|breve)|obrigad[oa]|valeu|boa\s+(tarde|noite|semana)|falou)\b",
    re.IGNORECASE,
)


def _detect_consecutive_farewells(history: list[dict], threshold: int = 2) -> bool:
    """Retorna True se as ultimas `threshold` mensagens do usuario forem despedidas."""
    user_msgs = [m for m in history if m.get("role") == "user"]
    if len(user_msgs) < threshold:
        return False
    last = user_msgs[-threshold:]
    return all(_FAREWELL_RE.search(m.get("content", "") or "") for m in last)
```

**Edit B** — Dentro de `run_agent`, antes de chamar o LLM, se `_detect_consecutive_farewells(history)` for True E `is_session_closed(conversation_id)` for False, forçar:

```python
if _detect_consecutive_farewells(history):
    from backend.app.agent.session_state import is_session_closed, set_session_closed
    if not await is_session_closed(conversation_id):
        await set_session_closed(conversation_id, "despedidas_consecutivas_detectadas")
        logger.info("[orchestrator] forced session close on consecutive farewells: %s", conversation_id)
        return AgentResult(messages=[], tool_calls=[], closed=True)
```

(Ajuste o tipo de retorno conforme a classe já usada em `orchestrator.py`. Se não houver campo `closed`, adicione-o ao dataclass.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_orchestrator_session_controls.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/agent/test_orchestrator_session_controls.py
git commit -m "feat(orchestrator): auto-close session on 2 consecutive user farewells"
```

---

## Task 9: Injetar bloco `[ESTADO DA SESSÃO]` no prompt (P2-A)

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Modify: `backend/tests/agent/test_orchestrator_session_controls.py`

**Motivação (R1 amnésia):** O LLM repete perguntas porque perde noção de turno, stage atual e fotos já enviadas. Injetar bloco sintético no system prompt a cada turno.

- [ ] **Step 1: Write the failing test**

Acrescentar:

```python
def test_build_session_state_block_includes_key_fields():
    from backend.app.agent.orchestrator import _build_session_state_block
    block = _build_session_state_block(
        turn=5,
        max_turns=20,
        stage="private_label",
        fotos_enviadas=["private_label"],
        farewells=1,
    )
    assert "turno 5/20" in block
    assert "stage=private_label" in block
    assert "fotos_enviadas=[private_label]" in block
    assert "despedidas_consecutivas=1" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_orchestrator_session_controls.py::test_build_session_state_block_includes_key_fields -v`
Expected: FAIL.

- [ ] **Step 3: Add builder and injection**

Em `backend/app/agent/orchestrator.py`:

```python
def _build_session_state_block(
    turn: int,
    max_turns: int,
    stage: str,
    fotos_enviadas: list[str],
    farewells: int,
) -> str:
    fotos_repr = "[" + ",".join(fotos_enviadas) + "]"
    return (
        f"[ESTADO DA SESSAO: turno {turn}/{max_turns}, stage={stage}, "
        f"fotos_enviadas={fotos_repr}, despedidas_consecutivas={farewells}]"
    )
```

Dentro de `run_agent`, após montar o `system_prompt` base, concatenar o bloco:

```python
state_block = _build_session_state_block(
    turn=current_turn,
    max_turns=MAX_TURNS,
    stage=current_stage,
    fotos_enviadas=session.get("fotos_enviadas", []),
    farewells=session.get("farewells_consecutivos", 0),
)
system_prompt = f"{system_prompt}\n\n{state_block}"
```

(Se `session` ainda não rastreia `fotos_enviadas` ou `farewells_consecutivos`, adicionar seta simples em Redis na mesma função.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_orchestrator_session_controls.py::test_build_session_state_block_includes_key_fields -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/agent/test_orchestrator_session_controls.py
git commit -m "feat(orchestrator): inject [ESTADO DA SESSAO] block each turn (fixes amnesia)"
```

---

## Task 10: Stage lock após primeira transição (P2-B)

**Files:**
- Modify: `backend/app/agent/tools.py`
- Modify: `backend/tests/agent/test_tools_encerrar_sessao.py` (reaproveitar arquivo para cobrir tools)

**Motivação (R1 flapping):** A Valéria trocou de `atacado` para `private_label` e vice-versa várias vezes. `mudar_stage` precisa ser removido das tools disponíveis após a primeira transição para um funil definitivo (qualquer stage ≠ `secretaria`).

- [ ] **Step 1: Write the failing test**

Acrescentar em `backend/tests/agent/test_tools_encerrar_sessao.py`:

```python
def test_mudar_stage_absent_after_lock():
    from backend.app.agent.tools import get_tools_for_stage
    # No stage inicial, mudar_stage deve existir
    initial = [t["function"]["name"] for t in get_tools_for_stage("secretaria")]
    assert "mudar_stage" in initial

    # Apos travar, mudar_stage nao deve estar disponivel
    locked = [t["function"]["name"] for t in get_tools_for_stage("atacado", stage_locked=True)]
    assert "mudar_stage" not in locked

    # Sem a trava explicita, ainda existe (comportamento atual)
    unlocked = [t["function"]["name"] for t in get_tools_for_stage("atacado", stage_locked=False)]
    assert "mudar_stage" in unlocked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_tools_encerrar_sessao.py::test_mudar_stage_absent_after_lock -v`
Expected: FAIL — assinatura atual não aceita `stage_locked`.

- [ ] **Step 3: Update `get_tools_for_stage` signature**

Em `backend/app/agent/tools.py`:

```python
def get_tools_for_stage(stage: str, *, stage_locked: bool = False) -> list[dict]:
    base = _STAGE_TOOLS.get(stage, _STAGE_TOOLS["secretaria"])
    names = list(base)
    if stage_locked and "mudar_stage" in names:
        names = [n for n in names if n != "mudar_stage"]
    return [_TOOL_BY_NAME[n] for n in names]
```

Em `orchestrator.py`, antes de chamar `get_tools_for_stage`, calcular:

```python
stage_locked = current_stage != "secretaria"
tools = get_tools_for_stage(current_stage, stage_locked=stage_locked)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests/agent/test_tools_encerrar_sessao.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/app/agent/orchestrator.py backend/tests/agent/test_tools_encerrar_sessao.py
git commit -m "feat(agent): lock stage after first non-secretaria transition (fixes flapping)"
```

---

## Task 11: Full regression suite

**Files:** (none)

**Objetivo:** Confirmar que nenhum teste existente quebrou.

- [ ] **Step 1: Run full suite**

Run: `cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && python -m pytest backend/tests -v`
Expected: 100% PASS (exceto testes marcados `skip`).

- [ ] **Step 2: If any failure not caused by this plan**

Stop. Abra um Todo separado. Não tente "enquanto estou aqui" fixar.

- [ ] **Step 3: Commit (only if lockfile / formatting changes)**

Se apareceu algo trivial tipo formatação auto do editor, commit separado:

```bash
git add -u
git commit -m "chore: post-rehearsal-fixes lint/format cleanup"
```

---

## Execução — Ordem Recomendada

1. **Tasks 1 → 11 sequenciais.** Cada task comita sozinha para facilitar revert granular.
2. **⚠️ NÃO rodar `rehearsal_runner.py`.** O usuário executa a bateria completa manualmente após todas as tasks estarem comitadas.
3. Ao final, avisar o usuário: "correções aplicadas e commitadas em `master` local. Pronto para você rodar a bateria de rehearsal manualmente e validar."

---

## Self-Review

**Spec coverage:**
- P1 (R3 loop) → Tasks 7 (encerrar_sessao) + 8 (farewell detection) + 6 (torra externa rota). ✓
- P2 (R1 amnésia/flapping/PRECO_FRETE) → Tasks 2 (regra 12) + 4 (atacado "gira em torno") + 9 (estado da sessão) + 10 (stage lock). ✓
- P3 (R5 B2B sample hallucination) → Tasks 3 (base.py amostra) + 4 (atacado reativo) + 5 (private_label KITS). ✓
- P4 (R2 crash silencioso) → Task 1 (instrumentação). ✓

**Placeholder scan:** Sem TBD, sem "similar to Task N", todos os snippets são completos.

**Type consistency:** `get_tools_for_stage` assina `(stage, *, stage_locked=False)` consistente entre Tasks 7 e 10. `_build_session_state_block` assinatura única na Task 9. `encerrar_sessao` nome consistente em Tasks 7 e 8.

**Directive compliance:**
- Decisão 1 (PRECO_FRETE) honrada em Tasks 2 + 4. Regex forbids.py não foi alterado. ✓
- Decisão 2 (amostra reativa, sem RAG loader) honrada em Tasks 3/4/5. Nenhuma task lê CSV. ✓
- Decisão 3 (instrumentar, não rodar) honrada em Task 1 + instrução final. ✓

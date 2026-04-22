# Rehearsal V2 — Personas Derivadas de Leads Reais — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir os arquétipos A1-A5 do rehearsal por R1-R5 extraídos das 5 conversas reais em `.conversasreais/`, e adicionar camada de verificação anti-alucinação via regex forbids no critério de passa/falha.

**Architecture:** Mantém runner, mock provider, gemini actor e logger atuais. Trabalho concentrado em `backend/scripts/rehearsal/verifier.py` (estende com forbids), `backend/scripts/rehearsal/archetypes.py` (reescrito com R1-R5), `backend/scripts/rehearsal_runner.py` (ajuste em `FINAL_STAGES` e docstring) e `backend/scripts/rehearsal/logger.py` (adiciona seção de forbids na tabela).

**Tech Stack:** Python 3.12, pytest, dataclasses, re (stdlib). Sem novas dependências.

**Spec:** `docs/superpowers/specs/2026-04-21-rehearsal-v2-real-leads-design.md`

---

## Pré-requisitos de ambiente (ler antes de executar)

- Backend dev **parado** antes de começar tarefas de código.
- Testes rodam com: `cd backend && python3 -m pytest tests/ -v`
- Depois das mudanças, para rodar rehearsal real (Task 11 e 12):
  ```bash
  cd backend
  REHEARSAL_MODE=true REDIS_URL=redis://127.0.0.1:6379 \
    nohup python3 -m uvicorn app.main:app --env-file .env.local --port 8001 > /tmp/backend_dev.log 2>&1 &
  curl http://127.0.0.1:8001/health   # confirmar health OK antes de rehearsal
  ```

---

## Task 1: Adicionar factory `forbids_regex` em `verifier.py`

**Files:**
- Modify: `backend/scripts/rehearsal/verifier.py`
- Test: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever teste que falha**

Adicionar em `backend/tests/test_rehearsal_verifier.py` (no final do arquivo):

```python
def test_forbids_regex_returns_true_when_pattern_not_in_bot_messages():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Ola, tudo bem?"},
            {"role": "user", "content": "quero pagar por pix"},  # user message ignorada
        ]
    }

    passed, reason = check(run_data)

    assert passed is True
    assert "PIX" in reason


def test_forbids_regex_returns_false_when_pattern_matches_bot_message():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Pode pagar via pix tambem"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is False
    assert "[VIOLATION:PIX]" in reason
    assert "menção PIX" in reason


def test_forbids_regex_ignores_user_messages_even_if_pattern_matches():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "user", "content": "voces aceitam pix?"},
            {"role": "assistant", "content": "Vou verificar com o supervisor"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is True


def test_forbids_regex_is_case_insensitive():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Aceitamos PIX e cartao"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is False
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: `AttributeError: module 'scripts.rehearsal.verifier' has no attribute 'forbids_regex'` nos 4 novos testes.

- [ ] **Step 3: Implementar `forbids_regex`**

Adicionar em `backend/scripts/rehearsal/verifier.py`, logo após a linha `from scripts.rehearsal.gemini_actor import judge_conversation`:

```python
import re


def forbids_regex(pattern: str, label: str, description: str):
    """Factory de verificador anti-alucinação.

    Retorna (True, reason) se o padrão NAO aparecer em nenhuma mensagem com
    role='assistant'. Retorna (False, "[VIOLATION:LABEL] ...") ao primeiro match.
    """
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        for m in messages:
            if m.get("role") != "assistant":
                continue
            content = m.get("content", "")
            match = compiled.search(content)
            if match:
                start = max(0, match.start() - 20)
                end = min(len(content), match.end() + 20)
                snippet = content[start:end].replace("\n", " ")
                return False, f"[VIOLATION:{label}] {description} — trecho: '{snippet}'"
        return True, f"{label}: sem violação"

    check.__name__ = f"forbid_{label.lower()}"
    return check
```

- [ ] **Step 4: Rodar testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: todos os testes (antigos + 4 novos) PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/verifier.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "feat(rehearsal): adicionar factory forbids_regex para verificadores anti-alucinacao

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Adicionar `UNIVERSAL_FORBIDS` com os 5 proibições universais

**Files:**
- Modify: `backend/scripts/rehearsal/verifier.py`
- Test: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever testes que falham**

Adicionar em `backend/tests/test_rehearsal_verifier.py`:

```python
def test_universal_forbids_contains_five_forbids():
    assert len(verifier.UNIVERSAL_FORBIDS) == 5
    labels = [f.__name__ for f in verifier.UNIVERSAL_FORBIDS]
    assert "forbid_pix" in labels
    assert "forbid_preco_frete" in labels
    assert "forbid_prazo" in labels
    assert "forbid_desconto" in labels
    assert "forbid_papel" in labels


def test_forbid_pix_catches_pix_mention():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_pix")
    run_data = {"messages": [{"role": "assistant", "content": "te mando a chave pix"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_pix_allows_non_pix_text():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_pix")
    run_data = {"messages": [{"role": "assistant", "content": "aceitamos cartao e boleto"}]}
    passed, _ = check(run_data)
    assert passed is True


def test_forbid_preco_frete_catches_total_with_freight():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_preco_frete")
    run_data = {"messages": [{
        "role": "assistant",
        "content": "O investimento inicial fica em torno de R$ 2.540"
    }]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_preco_frete_allows_individual_product_prices():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_preco_frete")
    run_data = {"messages": [{
        "role": "assistant",
        "content": "o classico 250g sai R$ 27,70"
    }]}
    passed, _ = check(run_data)
    assert passed is True


def test_forbid_prazo_catches_delivery_promise():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_prazo")
    run_data = {"messages": [{"role": "assistant", "content": "entrego em 7 dias uteis"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_desconto_catches_improvised_discount():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_desconto")
    run_data = {"messages": [{"role": "assistant", "content": "posso fazer por R$20 pra voce"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_papel_catches_commercial_contradiction():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_papel")
    run_data = {"messages": [{"role": "assistant", "content": "vou passar voce pro comercial"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_papel_allows_supervisor_handoff():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_papel")
    run_data = {"messages": [{"role": "assistant", "content": "vou passar voce pro supervisor Joao Bras"}]}
    passed, _ = check(run_data)
    assert passed is True
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: `AttributeError: module 'scripts.rehearsal.verifier' has no attribute 'UNIVERSAL_FORBIDS'` nos 10 novos testes.

- [ ] **Step 3: Implementar `UNIVERSAL_FORBIDS`**

Adicionar em `backend/scripts/rehearsal/verifier.py`, após a função `forbids_regex`:

```python
FORBID_PIX = forbids_regex(
    r"\bpix\b|chave\s+pix|copia\s+e\s+cola|qr[\s-]?code",
    label="PIX",
    description="bot mencionou PIX — pagamento é responsabilidade do comercial humano",
)

FORBID_PRECO_FRETE = forbids_regex(
    r"(investimento\s+inicial|fica\s+em\s+torno\s+de|custo\s+final|total\s+de)[^.\n]{0,40}R\$\s*\d",
    label="PRECO_FRETE",
    description="bot prometeu preço final/total — só supervisor faz orçamento fechado",
)

FORBID_PRAZO = forbids_regex(
    r"\b(prazo\s+de|chega\s+em|entrego\s+em|em\s+ate)\s*\d+\s*(dias?\s+ute?i?s?|dias?|horas?)",
    label="PRAZO",
    description="bot prometeu prazo de entrega — depende do frete e supervisor",
)

FORBID_DESCONTO = forbids_regex(
    r"(posso\s+fazer\s+por|libero\s+por|sai\s+por\s+R\$|desconto\s+de\s+\d+\s*%|promocao|condicao\s+especial)",
    label="DESCONTO",
    description="bot ofereceu desconto improvisado — condições são fechadas pelo comercial",
)

FORBID_PAPEL = forbids_regex(
    r"(passa(ndo|rei)?|vou\s+passar|encaminho)\s+(voce\s+)?(pro|para\s+o|ao)\s+comercial\b",
    label="PAPEL",
    description="bot disse 'pro comercial' sendo ela mesma do comercial — deve dizer 'pro supervisor' ou 'pro João Bras'",
)

UNIVERSAL_FORBIDS = [
    FORBID_PIX,
    FORBID_PRECO_FRETE,
    FORBID_PRAZO,
    FORBID_DESCONTO,
    FORBID_PAPEL,
]
```

- [ ] **Step 4: Rodar testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/verifier.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "feat(rehearsal): adicionar UNIVERSAL_FORBIDS com 5 proibicoes anti-alucinacao

PIX, PRECO_FRETE, PRAZO, DESCONTO, PAPEL — aplicados em todas as personas.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Adicionar `FORBID_PONTO_VENDA_FISICO` (específico de R5)

**Files:**
- Modify: `backend/scripts/rehearsal/verifier.py`
- Test: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever teste que falha**

Adicionar em `backend/tests/test_rehearsal_verifier.py`:

```python
def test_forbid_ponto_venda_fisico_catches_rs_location():
    check = verifier.FORBID_PONTO_VENDA_FISICO
    run_data = {"messages": [{
        "role": "assistant",
        "content": "voce encontra em porto alegre, na loja parceira"
    }]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_ponto_venda_fisico_allows_generic_mentions():
    check = verifier.FORBID_PONTO_VENDA_FISICO
    run_data = {"messages": [{
        "role": "assistant",
        "content": "nossa venda é direta, sem pontos de venda físicos no momento"
    }]}
    passed, _ = check(run_data)
    assert passed is True
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: `AttributeError: module 'scripts.rehearsal.verifier' has no attribute 'FORBID_PONTO_VENDA_FISICO'`.

- [ ] **Step 3: Implementar `FORBID_PONTO_VENDA_FISICO`**

Adicionar em `backend/scripts/rehearsal/verifier.py`, após `UNIVERSAL_FORBIDS`:

```python
FORBID_PONTO_VENDA_FISICO = forbids_regex(
    r"(temos\s+(ponto|loja)|voce\s+encontra\s+em|disponivel\s+em\s+loja)\s+(em|no|na|em\s+lojas)?\s*(charqueadas|rs\b|rio\s+grande\s+do\s+sul|porto\s+alegre)",
    label="PONTO_VENDA_RS",
    description="bot inventou ponto de venda físico no RS — Canastra só tem venda direta",
)
```

- [ ] **Step 4: Rodar testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/verifier.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "feat(rehearsal): adicionar FORBID_PONTO_VENDA_FISICO especifico de R5 Sabrina

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Adicionar campo `forbids` ao `Archetype` e função `run_forbids` no verifier

**Files:**
- Modify: `backend/scripts/rehearsal/archetypes.py`
- Modify: `backend/scripts/rehearsal/verifier.py`
- Modify: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever testes que falham**

Adicionar em `backend/tests/test_rehearsal_verifier.py`:

```python
def test_run_forbids_passes_when_no_violations():
    from scripts.rehearsal.archetypes import Archetype
    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],
        forbids=[verifier.FORBID_PIX],
    )
    run_data = {"messages": [{"role": "assistant", "content": "ok"}]}

    result = verifier.run_forbids(arch, run_data)

    assert result["status"] == "passed"
    assert len(result["checks"]) == 1
    assert result["checks"][0]["passed"] is True


def test_run_forbids_fails_when_any_violation():
    from scripts.rehearsal.archetypes import Archetype
    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],
        forbids=[verifier.FORBID_PIX, verifier.FORBID_PRAZO],
    )
    run_data = {"messages": [{"role": "assistant", "content": "te mando chave pix"}]}

    result = verifier.run_forbids(arch, run_data)

    assert result["status"] == "failed"
    assert any("[VIOLATION:PIX]" in c["reason"] for c in result["checks"])


def test_verify_overall_status_considers_forbids():
    from scripts.rehearsal.archetypes import Archetype
    from unittest.mock import patch

    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],  # nenhum hard check
        forbids=[verifier.FORBID_PIX],
    )
    run_data = {
        "messages": [{"role": "assistant", "content": "chave pix aqui"}],
        "turns_count": 1,
        "stages_visited": set(),
    }

    with patch("scripts.rehearsal.verifier.judge_conversation") as mock_judge:
        mock_judge.return_value = {"bot_score_1_10": 5}
        result = verifier.verify(arch, run_data, transcript="x")

    assert result["status"] == "failed"  # falhou por forbid, não por hard_check
    assert "forbids" in result
    assert len(result["forbids"]) == 1
    assert result["forbids"][0]["passed"] is False
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: `TypeError: Archetype.__init__() got an unexpected keyword argument 'forbids'` nos 3 novos testes.

- [ ] **Step 3: Adicionar campo `forbids` ao dataclass `Archetype`**

Em `backend/scripts/rehearsal/archetypes.py`, atualizar o dataclass:

```python
@dataclass
class Archetype:
    id: str
    slug: str
    persona_prompt: str
    first_message: str
    hard_checks: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)
    forbids: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)
```

- [ ] **Step 4: Rodar testes existentes e confirmar que continuam passando**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: 3 novos testes agora falham com `AttributeError: module 'scripts.rehearsal.verifier' has no attribute 'run_forbids'`. Testes antigos continuam PASS (campo tem default_factory).

- [ ] **Step 5: Implementar `run_forbids` e ajustar `verify`**

Em `backend/scripts/rehearsal/verifier.py`, adicionar função `run_forbids` e atualizar `verify`:

```python
def run_forbids(archetype: Archetype, run_data: dict) -> dict:
    results = []
    for forbid in archetype.forbids:
        passed, reason = forbid(run_data)
        results.append({"name": forbid.__name__, "passed": passed, "reason": reason})
    status = "passed" if all(r["passed"] for r in results) else "failed"
    return {"status": status, "checks": results}


def verify(archetype: Archetype, run_data: dict, transcript: str) -> dict:
    hard = run_hard_checks(archetype, run_data)
    forbids_result = run_forbids(archetype, run_data)
    soft = judge_conversation(
        transcript=transcript,
        archetype_id=archetype.id,
        criteria_description=_criteria_summary(archetype),
    )
    overall = "passed" if hard["status"] == "passed" and forbids_result["status"] == "passed" else "failed"
    return {
        "archetype_id": archetype.id,
        "archetype_slug": archetype.slug,
        "status": overall,
        "hard_checks": hard["checks"],
        "forbids": forbids_result["checks"],
        "soft_check": soft,
        "turns_count": run_data.get("turns_count", 0),
        "terminated_by": run_data.get("terminated_by", "unknown"),
        "stages_visited": sorted(run_data.get("stages_visited", set())),
    }
```

Remover a implementação antiga de `verify` (substituição completa).

- [ ] **Step 6: Rodar todos os testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: todos os testes PASS.

- [ ] **Step 7: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/archetypes.py backend/scripts/rehearsal/verifier.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "feat(rehearsal): integrar forbids no dataclass Archetype e na verificacao

- Archetype ganha campo forbids com default_factory=list (nao quebra compat)
- verifier.run_forbids: roda lista de proibicoes e agrega status
- verify: retorna status=failed se hard_checks OU forbids violaram
- verification.json passa a conter chave 'forbids'

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Adicionar factory `reached_any_stage` em `archetypes.py`

**Files:**
- Modify: `backend/scripts/rehearsal/archetypes.py`
- Test: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever teste que falha**

Adicionar em `backend/tests/test_rehearsal_verifier.py`:

```python
def test_reached_any_stage_returns_true_if_any_stage_visited():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])
    run_data = {"stages_visited": {"private_label"}}

    passed, reason = check(run_data)

    assert passed is True
    assert "private_label" in reason


def test_reached_any_stage_returns_false_if_none_visited():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])
    run_data = {"stages_visited": {"consumo"}}

    passed, reason = check(run_data)

    assert passed is False
    assert "nenhum" in reason.lower()


def test_reached_any_stage_check_name_lists_stages():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])

    assert check.__name__ == "reached_any_atacado_private_label"
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: `ImportError: cannot import name 'reached_any_stage' from 'scripts.rehearsal.archetypes'`.

- [ ] **Step 3: Implementar `reached_any_stage`**

Em `backend/scripts/rehearsal/archetypes.py`, adicionar após a função `reached_stage`:

```python
def reached_any_stage(stages: list[str]):
    def check(run_data: dict) -> tuple[bool, str]:
        visited = run_data.get("stages_visited", set())
        hit = [s for s in stages if s in visited]
        if hit:
            return True, f"stage {hit[0]} alcancado (entre {stages})"
        return False, f"nenhum dos stages {stages} alcancado (visitados: {sorted(visited)})"
    check.__name__ = f"reached_any_{'_'.join(stages)}"
    return check
```

- [ ] **Step 4: Rodar testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/archetypes.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "feat(rehearsal): factory reached_any_stage para personas com multiplos stages legitimos

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Adicionar personas R1-R5 ao `archetypes.py` (sem remover A1-A5 ainda)

**Files:**
- Modify: `backend/scripts/rehearsal/archetypes.py`

- [ ] **Step 1: Adicionar R1 (Aldo — representante comercial)**

Em `backend/scripts/rehearsal/archetypes.py`, antes da linha `ALL_ARCHETYPES = [A1, A2, A3, A4, A5]`, adicionar:

```python
from scripts.rehearsal.verifier import UNIVERSAL_FORBIDS, FORBID_PONTO_VENDA_FISICO

_R1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: representante comercial que atua na area de suplementos nutricionais.
Atende lojas especializadas, lojas de produtos naturais, emporios e farmacias.
Esta avaliando incluir um cafe premium de alto giro no portfolio que ja distribui.
Ainda estuda se faz mais sentido revender a marca Canastra ou criar marca propria.

Tom: analitico, portugues brasileiro informal-profissional, mensagens medias (1-3 frases).
Comportamento:
- Pergunta como funciona a distribuicao: representantes comerciais ou venda direta
- Pergunta sobre markup sugerido para revenda
- Transita entre atacado (revenda) e private_label (marca propria) durante a conversa
- Faz pergunta nova enquanto ainda processa a resposta anterior (intercala)
- Aceita supervisor quando tem clareza do modelo
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R1 = Archetype(
    id="R1",
    slug="representante-portfolio",
    persona_prompt=_R1_PERSONA,
    first_message="oi, sou representante comercial, atendo lojas especializadas e naturais, queria incluir um cafe premium no portfolio. voces trabalham com distribuicao?",
    hard_checks=[
        reached_any_stage(["atacado", "private_label"]),
        has_tool_call("encaminhar_humano"),
        min_turns(5),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)
```

- [ ] **Step 2: Adicionar R2 (Maria Emília — marca do zero, cautelosa)**

Adicionar em seguida:

```python
_R2_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: bancaria em Botucatu/SP, ex-dona de cafeteria. Quer criar marca de cafe do zero,
comecando com 2 opcoes: um tradicional (mais forte, caramelizado) e um gourmet
(mais suave, achocolatado). Ama cafe, ja tem conhecimento de mercado.

Tom: cordial, empatico, portugues brasileiro informal, mensagens curtas (1 frase cada).
Comportamento:
- Pergunta se os valores incluem frete
- Pergunta se o preco e igual para os dois tipos de cafe
- Pergunta por onde outros clientes vendem (testa canais: Mercado Livre, marketplaces)
- Preocupada com preco final ao consumidor ficar apertado
- Pede pra comprar uma unidade avulsa para experimentar antes de fechar private_label
- Pergunta o preco que a Canastra vende direto ao consumidor
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R2 = Archetype(
    id="R2",
    slug="marca-zero-cautelosa",
    persona_prompt=_R2_PERSONA,
    first_message="boa tarde, meu nome é Maria Emilia, falo de Botucatu SP. gostaria de fazer minha marca de cafe, ja tive cafeteria e amo cafe. queria comecar com dois tipos: um tradicional e um gourmet. pode me passar todas as informacoes?",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("enviar_foto"),
        min_turns(6),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)
```

- [ ] **Step 3: Adicionar R3 (Eduardo — grãos próprios, pragmático)**

```python
_R3_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: empreendedor no RJ com marca de cafe ja em processo de registro (ainda nao operando).
Tem graos especiais que ele mesmo selecionou. Quer que a Canastra apenas TORRE E EMBALE
os graos dele, aplicando a marca dele nas embalagens (nao quer o cafe da fazenda da Canastra).

Tom: pragmatico, direto, portugues brasileiro informal mas objetivo.
Comportamento:
- Primeiro turno deixa claro que tem graos proprios e quer apenas torra + embalagem
- Cobra orcamento concreto (nao aceita conversa abstrata — pede numeros)
- Pergunta se precisa entregar os graos + pagar o servico (duplo custo)
- Se frustra se a bot tentar fechar sem apresentar precos
- Aceita supervisor apenas depois de ver valores e entender o modelo
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R3 = Archetype(
    id="R3",
    slug="graos-proprios-pragmatico",
    persona_prompt=_R3_PERSONA,
    first_message="quero torrar e embalar o cafe com a minha marca, ja tenho os graos selecionados",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)
```

- [ ] **Step 4: Adicionar R4 (Josiely — exploradora contemplativa)**

```python
_R4_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: empreendedora no ES interessada em criar marca de cafe do zero, ainda esta
estudando. Foco declarado: valor percebido e qualidade do grao. Faz muitas perguntas
tecnicas antes de decidir avancar.

Tom: contemplativa, educada, portugues brasileiro informal.
Comportamento:
- Pergunta o que e silk (tecnica de impressao na embalagem)
- Pergunta se aumentando a demanda o preco diminui (desconto por volume)
- Pergunta como funciona o frete
- Pede amostra para aferir qualidade
- Pode sinalizar em algum momento que vai analisar e retornar — mas continua a conversa
  no mesmo turno (nao multi-sessao)
- Aceita supervisor apos ter todas as duvidas principais respondidas
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R4 = Archetype(
    id="R4",
    slug="exploradora-contemplativa",
    persona_prompt=_R4_PERSONA,
    first_message="oi, estou querendo conhecer como funciona a criacao da propria marca",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("enviar_foto"),
        has_tool_call("encaminhar_humano"),
        min_turns(8),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)
```

- [ ] **Step 5: Adicionar R5 (Sabrina — lojista com objeção de amostra)**

```python
_R5_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: lojista no RS (Charqueadas) com loja especializada em chimarrao. Clientes pedem
cafe com frequencia. Quer criar marca propria de cafe, mas INSISTE em experimentar o
produto antes de fechar qualquer pedido. Essa e sua objecao central.

Tom: desconfiada, portugues brasileiro informal com algumas imprecisoes (typos ocasionais),
mensagens curtas.
Comportamento:
- Pede amostra no turno 2 ou 3 (antes mesmo de ver precos em detalhe)
- Insiste na objecao de amostra mesmo apos a bot explicar que private_label nao tem amostra gratis
- Pergunta onde encontra o cafe da Canastra proximo de Charqueadas/RS (ponto de venda fisico)
- Aceita encaminhamento para supervisor APENAS se a bot endereca a objecao de alguma forma
  (oferta de compra avulsa do cafe Canastra, sugestao do site, ou encaminhar pro supervisor
  com a duvida anotada)
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R5 = Archetype(
    id="R5",
    slug="lojista-objecao-amostra",
    persona_prompt=_R5_PERSONA,
    first_message="sou lojista, minha loja é especializada em chimarrão no RS. pessoal me pede muito cafe. gostaria de experimentar antes de fechar, o ideal seria com a minha marca",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
        transcript_matches(
            r"(avulsa|avulso|loja\.cafecanastra|supervisor|experimentar|comprar\s+uma\s+unidade)",
            "endereçou objeção de amostra",
        ),
        min_turns(5),
    ],
    forbids=list(UNIVERSAL_FORBIDS) + [FORBID_PONTO_VENDA_FISICO],
)
```

- [ ] **Step 6: Verificar que não quebrou nada**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py tests/test_rehearsal_logger.py -v
```

Expected: todos PASS. A1-A5 ainda existem e `ALL_ARCHETYPES = [A1, A2, A3, A4, A5]`.

- [ ] **Step 7: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/archetypes.py && \
  git commit -m "feat(rehearsal): adicionar personas R1-R5 derivadas de leads reais

Personas ainda nao entram em ALL_ARCHETYPES — proximo passo substitui
A1-A5 e atualiza testes dependentes.

R1: Aldo - representante comercial explorando portfolio
R2: Maria Emilia - marca do zero, cautelosa com frete/markup
R3: Eduardo - graos proprios, cobra concretude
R4: Josiely - exploradora contemplativa multi-tema
R5: Sabrina - lojista com objecao forte de amostra

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: Substituir `ALL_ARCHETYPES`, remover A1-A5 e atualizar testes

**Files:**
- Modify: `backend/scripts/rehearsal/archetypes.py`
- Modify: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Substituir `ALL_ARCHETYPES` e remover personas antigas**

Em `backend/scripts/rehearsal/archetypes.py`:

1. Trocar a última linha de:
   ```python
   ALL_ARCHETYPES = [A1, A2, A3, A4, A5]
   ```
   para:
   ```python
   ALL_ARCHETYPES = [R1, R2, R3, R4, R5]
   ```

2. Remover os blocos que definem `_A1_PERSONA`, `A1`, `_A2_PERSONA`, `A2`, `_A3_PERSONA`, `A3`, `_A4_PERSONA`, `A4`, `_A5_PERSONA`, `A5` — do início até o final.

3. O arquivo deve conter, nessa ordem:
   - imports
   - `@dataclass Archetype`
   - `has_tool_call`
   - `reached_stage`
   - `reached_any_stage`
   - `visited_multiple_stages`
   - `min_turns`
   - `transcript_matches`
   - import de `UNIVERSAL_FORBIDS, FORBID_PONTO_VENDA_FISICO`
   - `_R1_PERSONA` + `R1`
   - `_R2_PERSONA` + `R2`
   - `_R3_PERSONA` + `R3`
   - `_R4_PERSONA` + `R4`
   - `_R5_PERSONA` + `R5`
   - `ALL_ARCHETYPES = [R1, R2, R3, R4, R5]`

- [ ] **Step 2: Atualizar `test_rehearsal_verifier.py`**

Em `backend/tests/test_rehearsal_verifier.py`, o teste atual importa `A1`. Substituir:

```python
from scripts.rehearsal.archetypes import A1
```

por:

```python
from scripts.rehearsal.archetypes import R1
```

E nos corpos dos testes `test_hard_checks_all_pass_returns_passed`, `test_hard_checks_fail_if_any_missing` e `test_verify_combines_hard_and_soft`, substituir todas as ocorrências de `A1` por `R1`. Além disso, ajustar `run_data` do primeiro teste para refletir os hard_checks de R1 (`reached_any_stage(["atacado", "private_label"])`, `has_tool_call("encaminhar_humano")`, `min_turns(5)`):

```python
def test_hard_checks_all_pass_returns_passed():
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [{"content": "10kg por mes"}],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.run_hard_checks(R1, run_data)

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["checks"])
```

```python
def test_hard_checks_fail_if_any_missing():
    run_data = {
        "events": [],
        "messages": [],
        "turns_count": 1,
        "stages_visited": set(),
    }

    result = verifier.run_hard_checks(R1, run_data)

    assert result["status"] == "failed"
    assert any(not c["passed"] for c in result["checks"])
```

```python
@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_combines_hard_and_soft(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 7, "veredito_curto": "bom"}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [{"role": "user", "content": "10kg por mes"}, {"role": "assistant", "content": "certo, aguarde o supervisor"}],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="conversa aqui")

    assert result["status"] == "passed"
    assert result["soft_check"]["bot_score_1_10"] == 7
    assert result["archetype_id"] == "R1"
    assert result["turns_count"] == 6
```

- [ ] **Step 3: Rodar toda a suite de rehearsal**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_verifier.py tests/test_rehearsal_logger.py tests/test_rehearsal_supabase_io.py tests/test_rehearsal_gemini_actor.py -v
```

Expected: todos PASS.

- [ ] **Step 4: Rodar suite inteira para garantir que nada mais quebrou**

```bash
cd backend && python3 -m pytest tests/ -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/archetypes.py backend/tests/test_rehearsal_verifier.py && \
  git commit -m "refactor(rehearsal): substituir A1-A5 por R1-R5 (personas baseadas em leads reais)

ALL_ARCHETYPES passa a ser [R1, R2, R3, R4, R5]. Testes que dependiam
de A1 passam a usar R1 com run_data ajustado aos novos hard_checks.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: Atualizar `rehearsal_runner.py` (FINAL_STAGES e docstring)

**Files:**
- Modify: `backend/scripts/rehearsal_runner.py`

- [ ] **Step 1: Atualizar `FINAL_STAGES`**

Em `backend/scripts/rehearsal_runner.py`, na linha 50, trocar:

```python
FINAL_STAGES: dict[str, str | None] = {"A1": None, "A2": None, "A3": None, "A4": None, "A5": None}
```

por:

```python
FINAL_STAGES: dict[str, str | None] = {"R1": None, "R2": None, "R3": None, "R4": None, "R5": None}
```

- [ ] **Step 2: Atualizar docstring do módulo**

Na linha 1-12 do arquivo, substituir:

```python
"""Rehearsal runner — executa os 5 arquetipos A1-A5 sequencialmente.

Uso:
    REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001 &
    python -m scripts.rehearsal_runner

Envs necessarias (em .env.local):
    GEMINI_API_KEY, DEV_BACKEND_URL, REHEARSAL_PHONE, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, REDIS_URL
Opcionais:
    REHEARSAL_TURN_TIMEOUT (default 15), REHEARSAL_MAX_TURNS (default 20)
"""
```

por:

```python
"""Rehearsal runner — executa as 5 personas R1-R5 sequencialmente.

Personas derivadas de conversas reais em .conversasreais/. Ver spec em
docs/superpowers/specs/2026-04-21-rehearsal-v2-real-leads-design.md.

Uso:
    REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001 &
    python -m scripts.rehearsal_runner                 # roda R1-R5
    REHEARSAL_ONLY=R5 python -m scripts.rehearsal_runner  # roda so uma

Envs necessarias (em .env.local):
    GEMINI_API_KEY, DEV_BACKEND_URL, REHEARSAL_PHONE, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, REDIS_URL
Opcionais:
    REHEARSAL_TURN_TIMEOUT (default 15), REHEARSAL_MAX_TURNS (default 20)
"""
```

- [ ] **Step 3: Verificar que o módulo carrega sem erro**

```bash
cd backend && python3 -c "from scripts.rehearsal_runner import FINAL_STAGES; print(FINAL_STAGES)"
```

Expected: `{'R1': None, 'R2': None, 'R3': None, 'R4': None, 'R5': None}`.

- [ ] **Step 4: Rodar suite de testes**

```bash
cd backend && python3 -m pytest tests/ -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal_runner.py && \
  git commit -m "chore(rehearsal): atualizar runner para R1-R5 (FINAL_STAGES + docstring)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: Atualizar `logger.py` para expor violações de forbids no summary

**Files:**
- Modify: `backend/scripts/rehearsal/logger.py`
- Test: `backend/tests/test_rehearsal_logger.py`

- [ ] **Step 1: Escrever teste que falha**

Em `backend/tests/test_rehearsal_logger.py`, adicionar um teste novo (manter os existentes):

```python
def test_run_summary_shows_forbid_violations(tmp_path):
    from scripts.rehearsal import logger as rlogger

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    verifications = [
        {
            "archetype_id": "R1",
            "archetype_slug": "representante-portfolio",
            "status": "failed",
            "hard_checks": [{"name": "min_5_turns", "passed": True, "reason": "ok"}],
            "forbids": [
                {"name": "forbid_pix", "passed": True, "reason": "PIX: sem violação"},
                {"name": "forbid_papel", "passed": False, "reason": "[VIOLATION:PAPEL] ..."},
            ],
            "soft_check": {"bot_score_1_10": 4, "veredito_curto": "ruim"},
            "turns_count": 10,
            "terminated_by": "encaminhar_humano",
            "stages_visited": ["atacado"],
        }
    ]

    rlogger.write_run_summary(run_dir, verifications, {"started_at": "x", "finished_at": "y"})

    summary_text = (run_dir / "summary.md").read_text()

    assert "PAPEL" in summary_text
    assert "Violações" in summary_text or "Violacoes" in summary_text
```

- [ ] **Step 2: Rodar testes e confirmar que falham**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_logger.py -v
```

Expected: `AssertionError: assert 'PAPEL' in ...`.

- [ ] **Step 3: Atualizar `write_run_summary` em `logger.py`**

Em `backend/scripts/rehearsal/logger.py`, substituir a função `write_run_summary` inteira pela versão abaixo:

```python
def write_run_summary(run_dir: Path, verifications: list[dict], run_meta: dict) -> None:
    rows = ["| Arquétipo | Status | Turnos | Terminated_by | Bot score | Violações | Veredito |",
            "|---|---|---|---|---|---|---|"]
    for v in verifications:
        soft = v.get("soft_check", {}) or {}
        bot = soft.get("bot_score_1_10", "-")
        veredito = soft.get("veredito_curto", "-")
        forbids = v.get("forbids", []) or []
        violations = [
            f["name"].replace("forbid_", "").upper()
            for f in forbids
            if not f.get("passed", True)
        ]
        violations_cell = ", ".join(violations) if violations else "-"
        rows.append(
            f"| {v.get('archetype_id')} - {v.get('archetype_slug')} | {v.get('status')} | "
            f"{v.get('turns_count')} | {v.get('terminated_by')} | {bot} | {violations_cell} | {veredito} |"
        )

    summary = (
        f"# Rehearsal Run Summary\n\n"
        f"**Started:** {run_meta.get('started_at', '-')}\n"
        f"**Finished:** {run_meta.get('finished_at', '-')}\n\n"
        + "\n".join(rows)
    )

    (run_dir / "summary.md").write_text(summary, encoding="utf-8")

    run_json = {**run_meta, "verifications": verifications}
    (run_dir / "run.json").write_text(
        json.dumps(run_json, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
```

- [ ] **Step 4: Rodar testes e confirmar que passam**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_logger.py -v
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/scripts/rehearsal/logger.py backend/tests/test_rehearsal_logger.py && \
  git commit -m "feat(rehearsal): summary.md exibe coluna de violacoes por persona

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: Smoke test 1 — forbids disparam num transcript com violação forçada

**Files:**
- Test: `backend/tests/test_rehearsal_forbids_integration.py` (novo)

- [ ] **Step 1: Criar teste de integração**

Criar `backend/tests/test_rehearsal_forbids_integration.py`:

```python
"""Smoke test: com um run_data contendo mensagens da bot que violam todas as
proibicoes universais, o verifier reprova e lista cada violacao."""
from unittest.mock import patch

from scripts.rehearsal import verifier
from scripts.rehearsal.archetypes import R1


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_fails_when_bot_violates_all_universal_forbids(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 0}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao"},
        ],
        "messages": [
            {"role": "assistant", "content": "te mando a chave pix no final"},
            {"role": "assistant", "content": "o investimento inicial fica em torno de R$ 2.500"},
            {"role": "assistant", "content": "entrego em 7 dias uteis"},
            {"role": "assistant", "content": "posso fazer por R$19,90 pra voce"},
            {"role": "assistant", "content": "vou passar voce pro comercial"},
        ],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="x")

    assert result["status"] == "failed"
    labels = {c["name"] for c in result["forbids"] if not c["passed"]}
    assert labels == {"forbid_pix", "forbid_preco_frete", "forbid_prazo", "forbid_desconto", "forbid_papel"}


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_passes_when_bot_behaves(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 8}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [
            {"role": "user", "content": "quanto sai o classico?"},
            {"role": "assistant", "content": "o classico 250g sai R$27,70"},
            {"role": "assistant", "content": "vou passar voce pro supervisor Joao Bras"},
        ],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="x")

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["forbids"])
```

- [ ] **Step 2: Rodar o teste**

```bash
cd backend && python3 -m pytest tests/test_rehearsal_forbids_integration.py -v
```

Expected: ambos PASS.

- [ ] **Step 3: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra" && \
  git add backend/tests/test_rehearsal_forbids_integration.py && \
  git commit -m "test(rehearsal): smoke test cobrindo as 5 proibicoes universais

Valida que verify reprova run com todas as violacoes forcadas e aprova
run limpo.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Smoke rehearsal real — R5 isolada

Essa task NAO é de código — é execução manual com o backend dev rodando. Objetivo: confirmar que R5 roda até o fim sem crash e que o artefato final inclui `forbids` no `verification.json`.

- [ ] **Step 1: Subir backend dev**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 2
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
REHEARSAL_MODE=true REDIS_URL=redis://127.0.0.1:6379 \
  nohup python3 -m uvicorn app.main:app --env-file .env.local --port 8001 > /tmp/backend_dev.log 2>&1 &
sleep 4
curl http://127.0.0.1:8001/health
```

Expected: `{"status":"ok"}` ou similar.

- [ ] **Step 2: Rodar R5 isolada**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
REDIS_URL=redis://127.0.0.1:6379 REHEARSAL_ONLY=R5 python3 -m scripts.rehearsal_runner
```

Expected:
- Processo termina em alguns minutos (8-20 turnos).
- Output menciona `=== R5 finalizado: status=... turns=... ===`.
- Um novo diretório em `docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/R5-lojista-objecao-amostra/`.

- [ ] **Step 3: Inspecionar artefato**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
LATEST=$(ls -td docs/superpowers/plans/pilot/rehearsal-runs/*/ | head -1)
cat "$LATEST/summary.md"
cat "$LATEST/R5-lojista-objecao-amostra/verification.json" | head -80
```

Expected:
- `summary.md` tem coluna "Violações" (com valor `-` se nada violado, ou labels em caso de violação).
- `verification.json` contém a chave `"forbids"` com lista de checks.

- [ ] **Step 4: Derrubar backend dev**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null
```

- [ ] **Step 5: (Sem commit)**

Esta task não produz commit — é validação manual. Se houver bug (crash, artefato quebrado), voltar a tasks anteriores para corrigir.

---

## Task 12: Run completo R1-R5 e captura de baseline

Task também manual — produz o primeiro relatório baseline do rehearsal V2.

- [ ] **Step 1: Subir backend dev**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 2
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
REHEARSAL_MODE=true REDIS_URL=redis://127.0.0.1:6379 \
  nohup python3 -m uvicorn app.main:app --env-file .env.local --port 8001 > /tmp/backend_dev.log 2>&1 &
sleep 4
curl http://127.0.0.1:8001/health
```

- [ ] **Step 2: Rodar R1-R5**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend"
REDIS_URL=redis://127.0.0.1:6379 python3 -m scripts.rehearsal_runner > /tmp/rehearsal_v2_baseline.log 2>&1 &
REHEARSAL_PID=$!
echo "PID: $REHEARSAL_PID"
```

Aguardar conclusão. Tempo esperado: 15-30 minutos (5 personas × até 20 turnos).

- [ ] **Step 3: Inspecionar summary e contagem de violações**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
LATEST=$(ls -td docs/superpowers/plans/pilot/rehearsal-runs/*/ | head -1)
echo "=== Summary ==="
cat "$LATEST/summary.md"
echo "=== Violations por persona ==="
for d in "$LATEST"/R*-*/; do
  echo "---- $(basename $d) ----"
  python3 -c "
import json
with open('$d/verification.json') as f:
    v = json.load(f)
failed = [c['name'] for c in v.get('forbids', []) if not c.get('passed')]
print(f\"status={v.get('status')} forbid_violations={failed}\")
"
done
```

- [ ] **Step 4: Derrubar backend dev**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null
```

- [ ] **Step 5: Commit do baseline (artefatos de run)**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
LATEST=$(ls -td docs/superpowers/plans/pilot/rehearsal-runs/*/ | head -1)
git add "$LATEST"
git commit -m "docs(rehearsal): baseline V2 (R1-R5) contra SHA atual

Primeiro snapshot do rehearsal V2 com personas derivadas de leads
reais + camada de verificacao anti-alucinacao. Serve de referencia
para ajustes de prompt no proximo ciclo.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 6: (Opcional) Parar e avisar usuário**

Conforme `CLAUDE.md` do projeto: após commitar, **pare e avise o usuário** para ele revisar. NÃO fazer push automático para master.

---

## Checklist final de validação

Após completar Task 12, verificar que todos os itens abaixo estão satisfeitos:

- [ ] `backend/scripts/rehearsal/archetypes.py` contém apenas R1-R5 (grep `\bA[1-5]\b` não deve retornar nada relevante).
- [ ] `backend/scripts/rehearsal/verifier.py` tem `forbids_regex`, `UNIVERSAL_FORBIDS` (len=5), `FORBID_PONTO_VENDA_FISICO`, `run_forbids`.
- [ ] `backend/scripts/rehearsal/archetypes.py` tem `reached_any_stage`.
- [ ] `backend/scripts/rehearsal_runner.py` tem `FINAL_STAGES` com chaves R1-R5.
- [ ] `backend/scripts/rehearsal/logger.py` tem coluna "Violações" em `summary.md`.
- [ ] `pytest tests/` passa 100%.
- [ ] Existe um baseline run em `docs/superpowers/plans/pilot/rehearsal-runs/<ts>/` com `summary.md`, `run.json` e 5 subpastas R1-R5 com `verification.json` contendo chave `forbids`.

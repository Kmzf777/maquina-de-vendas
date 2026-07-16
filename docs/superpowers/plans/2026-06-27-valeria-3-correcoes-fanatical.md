# Valéria — 3 Correções (Fanatical Prospecting) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir três falhas de comportamento da Valéria no funil outbound de atacado: (1) não desqualificar auto-produtores/concorrentes, (2) cegueira de roteiro que ignora afirmações elípticas do lead, (3) follow-up same-day agressivo em lead frio sem interesse.

**Architecture:** Erros 1 e 2 são correções de PROMPT (apenas instrução ao LLM, sem novas tools) em `valeria_outbound/atacado.py`. Erro 3 é correção do MOTOR Python: propaga uma flag `warm` (interesse marcado) de `processor.py` → `service.schedule_followup` → `cadence.build_touch_jobs`; quando `warm=False`, suprime o toque T1 same-day e a cadência começa no T2 (dia seguinte).

**Tech Stack:** Python 3.11, FastAPI, pytest, Supabase (mockado nos testes). LLM: gemini-2.5-flash via OpenAI-compat.

## Global Constraints

- **Prompts (Erros 1 e 2):** TODA alteração de prompt DEVE seguir `gemini-prompting-strategies.md` — estrutura consistente com headings Markdown, instruções críticas no início, linguagem direta/precisa, e few-shot examples no formato já existente do arquivo. Não criar novas tools para o Erro 1; apenas instruir o LLM.
- **Voz da Valéria (já no `base.py`):** minúsculas, sem ponto final, bolhas separadas por `\n\n`, sem emoji. Exemplos novos devem respeitar isso.
- **Erro 3 — escopo mínimo:** NÃO reestruturar a cadência. Apenas adicionar a propagação da flag de interesse para suprimir o T1. `warm` deve ter default `True` para preservar todos os chamadores e testes existentes (`router.py`, `test_multitouch_cadence.py`, `test_outbound_perfeicao.py`).
- **Sem regressão inbound:** o prompt inbound de atacado e seus testes não podem mudar de comportamento.
- **Comandos de teste rodam de dentro de `backend/`** (imports usam `app.`). Ex.: `cd backend && python -m pytest tests/...`.
- **Commits:** ao final de cada tarefa. Mensagens em pt-BR, terminando com a linha de co-autoria padrão do repo.

---

### Task 1: Erro 1 — Desqualificação suave de produtor/concorrente (prompt outbound)

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/atacado.py` (seção de situações adversas + few-shot)
- Test: `backend/tests/test_valeria_prompt_correcoes_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT` (string).
- Produces: `ATACADO_PROMPT` passa a conter o gatilho de produtor/concorrente que orienta `registrar_sem_interesse_atual` e a exceção de private_label.

- [ ] **Step 0: Confirmar que `registrar_sem_interesse_atual` está disponível no stage atacado**

Run: `cd backend && python -c "from app.agent.tools import get_tools_for_stage; print([t['function']['name'] for t in get_tools_for_stage('atacado')])"`
Expected: a lista inclui `registrar_sem_interesse_atual` e `mudar_stage`. Se NÃO incluir `registrar_sem_interesse_atual`, parar e reportar — o plano assume que a tool já existe (regra 18 do `base.py`); não criar tool nova.

- [ ] **Step 1: Escrever o teste que falha (RED)**

Criar `backend/tests/test_valeria_prompt_correcoes_2026_06_27.py`:

```python
"""Erros 1 e 2 (Fanatical Prospecting): correções de prompt no funil outbound atacado.

Testes de conteúdo de prompt — verificam que a instrução crítica está presente na string,
seguindo o padrão de test_outbound_perfeicao.py (asserções de substring no prompt).
"""
from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT as INBOUND_ATACADO_PROMPT


def _norm(s: str) -> str:
    return s.lower()


# --- Erro 1: produtor/concorrente -> desqualificação suave ---

def test_outbound_atacado_tem_gatilho_produtor_concorrente():
    low = _norm(ATACADO_PROMPT)
    # reconhece o perfil auto-produtor/concorrente
    assert "produtor" in low or "produz" in low
    assert "concorrente" in low
    # exemplos elípticos cobertos
    assert "sou eu mesma" in low or "eu que produzo" in low


def test_outbound_atacado_produtor_dispara_sem_interesse_e_nao_converte():
    low = _norm(ATACADO_PROMPT)
    # a ação de desqualificação suave usa registrar_sem_interesse_atual (sem nova tool)
    assert "registrar_sem_interesse_atual" in low
    # postura: não tentar converter / não fazer diagnóstico de dor para esse perfil
    assert "nao tente converter" in low or "não tente converter" in low


def test_outbound_atacado_produtor_excecao_private_label():
    low = _norm(ATACADO_PROMPT)
    # única exceção: lead pede explicitamente private label / marca própria
    assert "private_label" in low or "private label" in low or "marca propria" in low or "marca própria" in low
```

- [ ] **Step 2: Rodar o teste para ver falhar**

Run: `cd backend && python -m pytest tests/test_valeria_prompt_correcoes_2026_06_27.py::test_outbound_atacado_produtor_dispara_sem_interesse_e_nao_converte -v`
Expected: FAIL (a string `registrar_sem_interesse_atual` / "não tente converter" ainda não existe no prompt).

- [ ] **Step 3: Implementar — adicionar o gatilho no prompt**

Em `backend/app/agent/prompts/valeria_outbound/atacado.py`, dentro de `## SITUACOES ADVERSAS`, ANTES de `### Cliente quer montar marca propria (Private Label)`, inserir:

```
### LEAD É PRODUTOR DE CAFÉ / CONCORRENTE — DESQUALIFICAÇÃO SUAVE (regra crítica)
Gatilho: o lead revela que ELE MESMO produz, planta, cultiva, torra ou já é a própria fonte do café
que vende. Sinais: "eu que produzo", "eu mesmo torro", "produzo meu próprio café", "sou produtor",
"tenho minha fazenda/marca de café", e respostas elípticas como "sou eu mesma" / "ja tenho, sou eu"
em resposta a pergunta sobre fornecedor.

Um auto-produtor NÃO é cliente de atacado — ele é par/concorrente, está fora do nosso ICP. NÃO tente
converter, NÃO faça diagnóstico de dor, NÃO apresente catálogo, NÃO insista. Gastar turnos tentando
virar esse lead é a falha — reconheça e encerre com elegância.

Ação (em um único turno):
1. Reconheça com respeito genuíno o trabalho dele (UMA bolha curta, sem bajulação).
2. Encerre a tentativa de atacado deixando a porta aberta e chame
   registrar_sem_interesse_atual(motivo="lead é auto-produtor/concorrente de café — fora do ICP de atacado").

ÚNICA EXCEÇÃO: se o lead pedir EXPLICITAMENTE serviço de marca própria / private label ("quero minha
marca", "private label", "quero que vocês torrem/embalem com a minha marca"), aí sim execute
mudar_stage("private_label"). Produzir o próprio café NÃO é o mesmo que querer private label — não
presuma a exceção sem o pedido explícito.
```

E em `<few_shot_examples>`, ao final (antes do fechamento `"""`), adicionar:

```
## Exemplo 7 — lead é auto-produtor: desqualificação suave (não converter)
User: "eu que produzo meu café"
Assistant: "que bacana, produtor de café é outro nível de relação com o que se vende"
"se um dia fizer sentido a gente trocar ideia, fico por aqui"
[chama registrar_sem_interesse_atual(motivo="lead é auto-produtor/concorrente de café — fora do ICP de atacado")]

Nota: reconheceu com respeito, deixou a porta aberta e encerrou — NÃO fez diagnóstico de dor nem
perguntou "você torra também ou só cultiva?" (isso seria gastar turno com lead fora do ICP).
```

- [ ] **Step 4: Rodar os testes do Erro 1 para ver passar (GREEN)**

Run: `cd backend && python -m pytest tests/test_valeria_prompt_correcoes_2026_06_27.py -k "produtor" -v`
Expected: PASS (3 testes do bloco Erro 1).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/atacado.py backend/tests/test_valeria_prompt_correcoes_2026_06_27.py
git commit -m "$(cat <<'EOF'
fix(valeria): desqualificação suave de produtor/concorrente no atacado outbound

Erro 1 (Fanatical Prospecting): auto-produtor está fora do ICP de atacado.
Prompt agora reconhece o perfil e encerra via registrar_sem_interesse_atual,
sem gastar turnos tentando converter. Exceção só para pedido explícito de
private label.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Erro 2 — Regra 30 anti-interrogação (reagir/validar antes da pergunta de valor)

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/atacado.py` (regra 30, linhas ~59-62, + few-shot)
- Test: `backend/tests/test_valeria_prompt_correcoes_2026_06_27.py` (adiciona testes ao arquivo da Task 1)

**Interfaces:**
- Consumes: `ATACADO_PROMPT` (outbound) e `INBOUND_ATACADO_PROMPT` (regressão).
- Produces: regra 30 do outbound passa a exigir REAGIR/VALIDAR a fala do lead antes da pergunta de valor.

- [ ] **Step 1: Escrever os testes que falham (RED)**

Adicionar ao final de `backend/tests/test_valeria_prompt_correcoes_2026_06_27.py`:

```python
# --- Erro 2: anti-interrogação / reagir antes da pergunta de valor ---

def test_outbound_atacado_regra30_exige_reagir_e_validar():
    low = _norm(ATACADO_PROMPT)
    # a regra de valor (WIIFM/regra 30) deve obrigar reagir/validar antes de perguntar
    assert "anti-interrogacao" in low or "anti-interrogação" in low
    assert "reaja" in low or "reagir" in low
    assert "valide" in low or "validar" in low
    # menciona explicitamente o risco da frase elíptica
    assert "eliptic" in low or "sou eu mesma" in low


def test_inbound_atacado_anti_interrogacao_preservada_sem_regressao():
    # regressão: o inbound já tinha a anti-interrogação (Etapa 1) e não pode perdê-la
    low = _norm(INBOUND_ATACADO_PROMPT)
    assert "anti-interrogacao" in low or "anti-interrogação" in low
    assert "reaja" in low or "reagir" in low
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_valeria_prompt_correcoes_2026_06_27.py::test_outbound_atacado_regra30_exige_reagir_e_validar -v`
Expected: FAIL (a regra 30 atual não menciona anti-interrogação/reagir/validar/elíptica).

- [ ] **Step 3: Implementar — reescrever a regra 30**

Em `backend/app/agent/prompts/valeria_outbound/atacado.py`, substituir o bloco atual da regra 30 (que começa em `WIIFM ANTES DO CATALOGO (regra 30):`) por:

```
WIIFM ANTES DO CATALOGO (regra 30): com lead que ja tem fornecedor e NAO declarou querer trocar,
faca PRIMEIRO uma pergunta de valor ("o que voce mais valoriza hoje no seu fornecedor?" / "tem algo
no atual que voce gostaria de melhorar?") e descubra a lacuna ANTES de mostrar produto ou preco. E
nessa lacuna que voce conecta o nosso diferencial.

ANTI-INTERROGACAO (obrigatoria — vem ANTES da pergunta de valor): REAJA e VALIDE o que o lead ACABOU
de dizer antes de disparar a pergunta de valor. Leia a ultima mensagem ao pe da letra — respostas
curtas ou ELIPTICAS ("sou eu mesma", "eu que faço", "ja tenho, sou eu") podem MUDAR completamente o
sentido. Se a frase indicar que o lead MESMO é a fonte/produtor do café, isso NAO é "tem fornecedor e
quer melhorar" — é o gatilho de DESQUALIFICAÇÃO SUAVE (ver a regra do produtor/concorrente em
SITUACOES ADVERSAS). NUNCA dispare a pergunta de valor de forma automatica sobre qualquer "ja tenho":
primeiro entenda e valide o que foi dito, depois pergunte.
```

E em `<few_shot_examples>`, adicionar (após o Exemplo 7 da Task 1):

```
## Exemplo 8 — reagir/validar antes da pergunta de valor (anti-cegueira de roteiro)
User: "já tenho fornecedor"
"sou eu mesma"
Assistant: "ah, entendi, então o café é todo seu, da produção até a ponta"
[reconhece o sentido real e cai na desqualificação suave — NAO pergunta "o que você gostaria de
melhorar no fornecedor?"]

Nota: "sou eu mesma" = ela é a propria fornecedora/produtora. Reagir ao sentido literal evita a
pergunta de valor robótica sobre um "fornecedor" que não existe.
```

- [ ] **Step 4: Rodar os testes do Erro 2 + suíte do arquivo (GREEN)**

Run: `cd backend && python -m pytest tests/test_valeria_prompt_correcoes_2026_06_27.py -v`
Expected: PASS (todos — Erro 1 e Erro 2, incluindo a regressão inbound).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/atacado.py backend/tests/test_valeria_prompt_correcoes_2026_06_27.py
git commit -m "$(cat <<'EOF'
fix(valeria): regra 30 anti-interrogação no atacado outbound

Erro 2 (cegueira de roteiro): a IA disparava a pergunta de valor scriptada
sobre qualquer "já tenho", ignorando o sentido real de frases elípticas como
"sou eu mesma". A regra 30 agora obriga reagir/validar a fala do lead antes
da pergunta de valor, conectando ao gatilho de produtor/concorrente.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Erro 3 — Suprimir T1 same-day para lead frio (sem interesse)

**Files:**
- Modify: `backend/app/follow_up/cadence.py` (`build_touch_jobs` ganha param `warm`)
- Modify: `backend/app/follow_up/service.py` (`schedule_followup` ganha param `warm`, repassa)
- Modify: `backend/app/buffer/processor.py:975` (passa `warm=bool(interest)`)
- Modify: `backend/tests/test_followup_gate.py` (atualiza assert para incluir `warm=True`)
- Test: `backend/tests/test_followup_cold_start_2026_06_27.py` (novo)

**Interfaces:**
- Consumes: `interest = pop_interest_marked(conversation["id"])` (dict ou None) já existente em `processor.py:848`.
- Produces:
  - `build_touch_jobs(now, conversation_id, lead_id, channel_id, env_tag, warm=True, rng=_random) -> list[dict]` — `warm=False` omite o toque sequence=1.
  - `schedule_followup(conversation_id, lead_id, channel_id, warm=True) -> None` — repassa `warm`.

- [ ] **Step 1: Escrever os testes da cadência que falham (RED)**

Criar `backend/tests/test_followup_cold_start_2026_06_27.py`:

```python
"""Erro 3: lead frio (sem interesse) não recebe o T1 same-day — cadência começa no T2."""
from datetime import datetime, timezone


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_cold_start_skips_t1_same_day():
    from app.follow_up.cadence import build_touch_jobs
    now = _utc(2026, 6, 29, 12, 0)  # Mon 09:00 BRT
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev", warm=False)
    # T1 (sequence 1, same-day) suprimido — cadência começa no T2
    assert [j["sequence"] for j in jobs] == [2, 3, 4]
    assert [j["metadata"]["objetivo"] for j in jobs] == [
        "reforco_valor", "prova_social", "ultima_chamada"
    ]
    # nenhum job dispara no mesmo dia do agendamento (29/06)
    for j in jobs:
        fire = datetime.fromisoformat(j["fire_at"])
        assert fire.date() > now.date(), f"job seq={j['sequence']} disparou same-day ({fire})"


def test_warm_start_keeps_full_cadence_default_true():
    from app.follow_up.cadence import build_touch_jobs
    now = _utc(2026, 6, 29, 12, 0)
    # default (warm=True) preserva os 4 toques, T1 same-day
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    assert [j["sequence"] for j in jobs] == [1, 2, 3, 4]
    assert datetime.fromisoformat(jobs[0]["fire_at"]).date() == now.date()
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_followup_cold_start_2026_06_27.py -v`
Expected: FAIL — `build_touch_jobs()` ainda não aceita `warm` (TypeError) / não suprime o T1.

- [ ] **Step 3: Implementar `warm` em `build_touch_jobs`**

Em `backend/app/follow_up/cadence.py`, alterar a assinatura e o loop:

```python
def build_touch_jobs(
    now: datetime,
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    env_tag: str,
    warm: bool = True,
    rng=_random,
) -> list[dict]:
    """Constrói os jobs da cadência com fire_at monotônico (>= MIN_GAP) e clampado.

    `warm=True` (default): cadência completa de 4 toques, com T1 same-day (offset 0 + jitter).
    `warm=False` (lead frio, sem interesse marcado): SUPRIME o T1 same-day — a cadência começa no
    T2 (dia seguinte). Anti-bombardeio: lead que só engajou (sem sinal de interesse) não recebe
    cobrança no mesmo dia.

    Função pura: sem I/O. `rng` injetável para teste do jitter do T1.
    """
    jobs: list[dict] = []
    prev_fire: datetime | None = None
    touches = CADENCE if warm else CADENCE[1:]
    for touch in touches:
        offset = touch.offset
        if touch.jitter_minutes:
            lo, hi = touch.jitter_minutes
            offset = offset + timedelta(minutes=rng.randint(lo, hi))
        fire_at = _clamp_to_business_window(now + offset)
        if prev_fire is not None and fire_at <= prev_fire + MIN_GAP:
            fire_at = _clamp_to_business_window(prev_fire + MIN_GAP)
        prev_fire = fire_at
        jobs.append({
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": touch.sequence,
            "fire_at": fire_at.isoformat(),
            "status": "pending",
            "env_tag": env_tag,
            "metadata": {
                "objetivo": touch.objective,
                "objective_prompt": touch.objective_prompt,
                "contexto": touch.objective,
            },
        })
    return jobs
```

- [ ] **Step 4: Rodar os testes da cadência (GREEN)**

Run: `cd backend && python -m pytest tests/test_followup_cold_start_2026_06_27.py tests/test_multitouch_cadence.py -v`
Expected: PASS (novos + os 4 toques default preservados).

- [ ] **Step 5: Propagar `warm` em `schedule_followup`**

Em `backend/app/follow_up/service.py`, alterar a assinatura e a chamada a `build_touch_jobs`:

```python
def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    warm: bool = True,
) -> None:
    """Cancela jobs pendentes anteriores desta conversa e insere a cadência via build_touch_jobs.

    `warm=True` (default): cadência completa (T1 same-day). `warm=False` (lead frio sem interesse):
    suprime o T1 — cadência começa no T2 (anti-bombardeio).
    """
```

E na linha que chama `build_touch_jobs` (atual `jobs = build_touch_jobs(now, conversation_id, lead_id, channel_id, _ENV_TAG)`):

```python
    jobs = build_touch_jobs(now, conversation_id, lead_id, channel_id, _ENV_TAG, warm=warm)
```

- [ ] **Step 6: Rodar testes de service para garantir sem regressão**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py tests/test_outbound_perfeicao.py -v`
Expected: PASS (chamadores sem `warm` continuam gerando os 4 jobs).

- [ ] **Step 7: Escrever o teste do processor que falha (RED)**

Criar `backend/tests/test_followup_warm_flag_2026_06_27.py`, espelhando o mock pattern de `test_followup_gate.py`:

```python
"""Erro 3 (processor): warm flag propagado a schedule_followup conforme interesse marcado."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_lead():
    return {"id": "lead-w", "phone": "+5511988887777", "stage": "atacado",
            "status": "active", "ai_enabled": True, "name": "Teste"}


def _make_channel():
    return {"id": "ch-w", "is_active": True, "mode": "ai",
            "agent_profiles": {"id": "p1", "stages": {}},
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _make_conversation():
    return {"id": "conv-w", "lead_id": "lead-w", "channel_id": "ch-w",
            "stage": "atacado", "status": "active", "followup_enabled": True}


def _make_supabase_mock():
    return MagicMock(table=MagicMock(return_value=MagicMock(
        update=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            execute=MagicMock(return_value=MagicMock()))))),
        select=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            single=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(data={"unread_count": 0})))))))),
    )))


def _mock_settings():
    s = MagicMock()
    s.ai_phone_number_id = None
    s.ai_phone_number_ids = frozenset()
    return s


@pytest.mark.asyncio
async def test_warm_true_when_interest_marked():
    interest_signal = {"nivel": "quente", "motivo": "perguntou preço"}
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="claro, te passo os valores"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=interest_signal), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._update_last_msg"):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511988887777", "qual o preço?", "ch-w")
        mock_followup.assert_called_once_with(
            conversation_id="conv-w", lead_id="lead-w", channel_id="ch-w", warm=True,
        )


@pytest.mark.asyncio
async def test_warm_false_when_outbound_engaged_without_interest():
    """Outbound engajou-e-esfriou sem interesse → agenda, mas warm=False (suprime T1 same-day)."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="boa, e como o café entra no seu negócio"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.pop_interest_marked", return_value=None), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]), \
         patch("app.buffer.processor.get_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_supabase", return_value=_make_supabase_mock()), \
         patch("app.buffer.processor.settings", _mock_settings()), \
         patch("app.buffer.processor._check_frustration_guardrail", return_value=False), \
         patch("app.buffer.processor._resolve_agent_persona", return_value="valeria_outbound"), \
         patch("app.buffer.processor._update_last_msg"):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511988887777", "meu negócio", "ch-w")
        mock_followup.assert_called_once_with(
            conversation_id="conv-w", lead_id="lead-w", channel_id="ch-w", warm=False,
        )
```

NOTA DE IMPLEMENTAÇÃO p/ Step 7: o `agent_persona` precisa ser `"valeria_outbound"` para o gatilho (2) disparar. Antes de escrever este teste, **abrir `processor.py` e localizar como `agent_persona` é resolvido** (grep `agent_persona =` em `processor.py`). Ajustar o patch de `_resolve_agent_persona` para o nome real da função/derivação. Se a persona vier de outra fonte (ex.: do profile do canal), ajustar o fixture do canal/`run_agent` para produzir `valeria_outbound` em vez do patch. O contrato testado é o que importa: **outbound sem interesse → `warm=False`**.

- [ ] **Step 8: Rodar para ver falhar**

Run: `cd backend && python -m pytest tests/test_followup_warm_flag_2026_06_27.py -v`
Expected: FAIL — `_schedule_followup` ainda é chamado sem `warm`.

- [ ] **Step 9: Implementar a propagação no processor**

Em `backend/app/buffer/processor.py`, na chamada a `_schedule_followup` (linha ~975), adicionar o kwarg `warm=bool(interest)`:

```python
                    if should_schedule:
                        try:
                            _schedule_followup(
                                conversation_id=conversation["id"],
                                lead_id=lead["id"],
                                channel_id=channel["id"],
                                warm=bool(interest),
                            )
                            logger.info("[FOLLOWUP] agendado (%s, warm=%s) para %s", reason, bool(interest), phone)
```

- [ ] **Step 10: Atualizar o assert do `test_followup_gate.py` (incluir warm)**

Em `backend/tests/test_followup_gate.py`, no `test_followup_scheduled_when_interest_marked`, atualizar a asserção (interest está marcado → `warm=True`):

```python
        mock_followup.assert_called_once_with(
            conversation_id="conv-fg-1",
            lead_id="lead-fg-1",
            channel_id="ch-fg-1",
            warm=True,
        )
```

- [ ] **Step 11: Rodar a suíte de follow-up completa (GREEN + regressão)**

Run: `cd backend && python -m pytest tests/test_followup_warm_flag_2026_06_27.py tests/test_followup_gate.py tests/test_followup_cold_start_2026_06_27.py tests/test_multitouch_cadence.py tests/test_outbound_perfeicao.py -v`
Expected: PASS (todos).

- [ ] **Step 12: Commit**

```bash
git add backend/app/follow_up/cadence.py backend/app/follow_up/service.py backend/app/buffer/processor.py backend/tests/test_followup_cold_start_2026_06_27.py backend/tests/test_followup_warm_flag_2026_06_27.py backend/tests/test_followup_gate.py
git commit -m "$(cat <<'EOF'
fix(followup): suprime T1 same-day para lead frio sem interesse

Erro 3: lead outbound que só engajou (sem marcar_interesse) recebia o T1 da
cadência no mesmo dia (offset 0 + jitter 90-210min) — cobrança agressiva em
lead frio. Agora processor propaga warm=bool(interest); warm=False omite o T1
e a cadência começa no T2 (dia seguinte). Lead quente mantém o T1 same-day.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Verificação final de regressão (suíte completa)

**Files:** nenhum (apenas execução)

- [ ] **Step 1: Rodar a suíte de testes do backend**

Run: `cd backend && python -m pytest -q`
Expected: toda a suíte verde (sem novas falhas vs. baseline). Atenção especial às suítes inbound (`test_inbound_autonomy_2026_06_26.py`) e de processor (`test_processor_*`).

- [ ] **Step 2: Se houver falha pré-existente não relacionada**

Confirmar (via `git stash` + re-run, ou comparando com a baseline) que a falha já existia antes destas mudanças. Documentar; não tentar consertar fora de escopo.

---

## Self-Review

**1. Spec coverage:**
- Erro 1 → Task 1 (prompt produtor/concorrente + `registrar_sem_interesse_atual`, exceção private_label). ✓
- Erro 2 → Task 2 (regra 30 anti-interrogação + few-shot elíptico). ✓
- Diretriz #3 (gemini-prompting-strategies) → Global Constraints + edições usam headings Markdown consistentes, instrução crítica no topo das seções, few-shot no formato existente. ✓
- Erro 3 → Task 3 (flag `warm` propagada processor→service→cadence, suprime T1). ✓
- Regressão inbound → Task 2 Step 1 (teste de preservação) + Task 4. ✓
- TDD Red-Green-Refactor → cada task escreve teste, vê falhar, implementa, vê passar. ✓
- Sem novas tools (Erro 1) → usa `registrar_sem_interesse_atual` existente (Step 0 confirma). ✓
- Sem reestruturar a cadência (Erro 3) → apenas `CADENCE[1:]` quando frio. ✓

**2. Placeholder scan:** sem TBD/TODO; todo código mostrado por extenso. Único ponto de investigação dirigida: Step 7 (nome real da resolução de `agent_persona`) — instrução explícita de como descobrir e o contrato a garantir.

**3. Type consistency:** `warm: bool = True` idêntico em `build_touch_jobs` e `schedule_followup`; processor passa `warm=bool(interest)`; assert do teste usa `warm=True`/`warm=False`. Sequências cold = `[2,3,4]` consistentes com `CADENCE[1:]`.

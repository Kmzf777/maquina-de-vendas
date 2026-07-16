# Valéria — Correções Fanatical Prospecting (Parte 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir 3 falhas confirmadas em produção no lead Johny (5519981518080): (1) pitch imediato na correção de nome, (2) múltiplos toques T1 same-day por re-armação da cadência, (3) alucinação temporal ("outro dia") no follow-up.

**Architecture:** Erro 1 é prompt (`secretaria.py`): separar "correção de nome" de "número errado". Erro 2 é lógica Python: trava de "já tocado hoje" no seam de I/O `schedule_followup` (service.py), forçando `warm=False` se já houve toque same-day hoje. Erro 3 é contexto ausente: injetar âncora temporal (Δt) no histórico e prompt do follow-up (scheduler.py) + grounding anti-invenção de período.

**Tech Stack:** Python 3.11, FastAPI, pytest + unittest.mock, Supabase (prod tshmvxxxyxgctrdkqvam), gemini-2.5-flash via OpenAI-compat.

## Global Constraints

- **Fluxo Git:** sem PRs. Branch local `fix/valeria-cadencia-fanatical-parte2`; commits na branch. NÃO fazer push/deploy nesta sessão sem autorização explícita.
- **Prompts:** QUALQUER alteração de prompt (Erro 1, Erro 3) DEVE seguir `gemini-prompting-strategies.md`: estrutura consistente (headings Markdown / tags), instruções diretas e precisas, instrução crítica no topo, few-shot com formato consistente, e a cláusula de grounding ("rely only on the facts… do not invent").
- **Escopo:** não alterar a estrutura do Supabase, não mexer no motor ReAct/orchestrator. Ajustes cirúrgicos nos fluxos específicos.
- **Persona/voz:** mensagens ao cliente em minúsculas, com acentos, sem ponto final, `\n\n` entre bolhas (regras do `base.py`). NÃO violar ao escrever exemplos de prompt.
- **Paridade de ambiente:** o código roda em Docker (prod) e host (dev) sem modificação. Sem `localhost` hardcoded.
- **TDD obrigatório:** Red → Green → Refactor em cada task. Rodar a suíte de follow-up + a suíte impactada a cada task.

---

### Task 1: Erro 1 — `secretaria.py` separa correção de nome de número errado

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/secretaria.py` (bloco "NAO e ele / NUMERO ERRADO", linhas ~96-102; e o few-shot/cenários)
- Test: `backend/tests/test_valeria_secretaria_nome_2026_06_27.py` (criar)

**Interfaces:**
- Consumes: constante `SECRETARIA_PROMPT` (string) exportada por `secretaria.py`.
- Produces: `SECRETARIA_PROMPT` contendo um cenário dedicado de **correção de nome** (warm/ponte de valor, sem pitch) distinto do cenário de **número errado / recusa** (1 linha + opt-out).

**Contexto da falha (produção, lead Johny):** o lead clicou "Não" + digitou "Johny" (nome real; o nome registrado estava errado). O script de número-errado disparou o pitch "mas se café especial direto da fazenda te interessar, é só falar, a gente trabalha com atacado…". Johny era lead válido (2h depois: "Gostaria de revender"). O gatilho `"nome diferente"` foi misturado com `"numero errado"`.

**Design da correção (segue `gemini-prompting-strategies.md`):**
- Dividir o cenário único em DOIS cenários explícitos e mutuamente exclusivos, com discriminador claro:
  - **CORREÇÃO DE NOME / IDENTIDADE** — lead clicou "Não" MAS se identificou com um nome próprio, OU disse "aqui é o/a X", "meu nome é Y", "quem fala é Y". É a pessoa certa com o nome errado no cadastro. Ação: `salvar_nome` IMEDIATO + PONTE DE VALOR da Regra de Ouro 0 (reconhecer o contato em 1 frase + situar a Café Canastra em 1 frase de valor concreto + UMA pergunta leve e aberta de interesse). PROIBIDO ofertar produto/atacado/preço direto. PROIBIDO opt-out.
  - **NÚMERO ERRADO / RECUSA SEM NOME** — lead diz "não sou eu", "número errado", "não conheço", sem se identificar. Mantém o comportamento atual: 1 linha de re-engajamento leve; se sem interesse/sem resposta → `registrar_optout`.
- Discriminador (1 linha, direto): "deu um nome próprio? → correção de nome. Negou sem se identificar? → número errado."
- Adicionar UM few-shot do caminho de correção de nome, no formato consistente do arquivo (User/Assistant), mostrando ponte de valor SEM pitch.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_valeria_secretaria_nome_2026_06_27.py
"""Erro 1 (parte 2): correção de nome no outbound NÃO dispara pitch imediato.

Produção (lead Johny 5519981518080): clicou "Não" + "Johny" (nome real). O script de
'número errado' disparou o pitch de atacado. Correção de nome deve salvar o nome e
construir a PONTE DE VALOR (Regra de Ouro 0), nunca ofertar produto direto.
"""
from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT


def test_separa_correcao_de_nome_de_numero_errado():
    low = SECRETARIA_PROMPT.lower()
    # Existe um cenário dedicado de correção de nome/identidade...
    assert "correcao de nome" in low or "correção de nome" in low
    # ...que manda salvar o nome e aquecer (ponte de valor), não ofertar produto.
    assert "salvar_nome" in low


def test_correcao_de_nome_proibe_pitch_e_optout_imediato():
    low = SECRETARIA_PROMPT.lower()
    # A seção de correção de nome deve referenciar a ponte de valor / aquecer.
    assert "ponte de valor" in low
    # E deve haver um few-shot do caminho de correção que NÃO oferta atacado de cara.
    assert "few_shot" in low or "exemplo" in low


def test_numero_errado_ainda_tem_caminho_de_optout():
    low = SECRETARIA_PROMPT.lower()
    # O caminho de número errado de fato (sem nome) preserva o opt-out.
    assert "registrar_optout" in low
    assert "numero errado" in low or "número errado" in low
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_valeria_secretaria_nome_2026_06_27.py -v`
Expected: FAIL — `test_separa_correcao_de_nome_de_numero_errado` falha (não há "correção de nome" como seção dedicada; hoje "nome diferente" está fundido com número errado).

- [ ] **Step 3: Implement — reescrever o bloco em `secretaria.py`**

Substituir o bloco atual (linhas ~96-102):

```
**NAO e ele / NUMERO ERRADO — botao "Nao" ou texto ("nao sou eu", "numero errado", nome diferente):**
Desculpe o engano e abra UMA chance de re-engajamento — NAO registre opt-out de imediato.
- "opa, desculpa o engano"
  "mas se cafe especial direto da fazenda te interessar, e so falar, a gente trabalha com atacado, marca propria e consumo"
Se a pessoa demonstrar QUALQUER curiosidade ou fizer perguntas → siga a qualificacao normalmente.
Se nao tiver interesse, pedir pra parar, ou nao responder → registrar_optout(motivo="numero incorreto — sem interesse").
NAO encerre antes de dar essa abertura.
```

por DOIS cenários distintos:

```
**CORRECAO DE NOME / IDENTIDADE — lead clicou "Nao" MAS se identificou com um nome proprio, ou disse "aqui e o/a X", "meu nome e Y", "quem fala e Y":**
DISCRIMINADOR: deu um nome proprio = e a PESSOA CERTA com o nome errado no cadastro (NAO e numero errado). Trate como lead valido.
Acao obrigatoria, nesta ordem:
1. Chame salvar_nome com o nome informado IMEDIATAMENTE (regra 20).
2. Construa a PONTE DE VALOR (Regra de Ouro 0), em bolhas curtas: reconheca o contato em 1 frase + situe a Cafe Canastra em 1 frase de valor concreto + UMA pergunta leve e aberta de interesse.
PROIBIDO ofertar produto, atacado, catalogo ou preco direto aqui. PROIBIDO registrar_optout. Aquecer vem ANTES de qualquer oferta.
- "opa, era esse cadastro que a gente queria confirmar, obrigada"
  "a gente e a torrefacao de cafe especial da Serra da Canastra, da fazenda pra xicara"
  "cafe faz mais parte do seu dia a dia ou do seu negocio?"

**NUMERO ERRADO / RECUSA SEM NOME — botao "Nao" ou texto ("nao sou eu", "numero errado", "nao conheco") SEM se identificar:**
DISCRIMINADOR: negou e NAO deu nenhum nome proprio. Aqui sim pode ser engano de numero.
Desculpe o engano e abra UMA chance de re-engajamento — NAO registre opt-out de imediato.
- "opa, desculpa o engano"
  "mas se cafe especial direto da fazenda te interessar, e so falar, a gente trabalha com atacado, marca propria e consumo"
Se a pessoa demonstrar QUALQUER curiosidade ou fizer perguntas → siga a qualificacao normalmente.
Se nao tiver interesse, pedir pra parar, ou nao responder → registrar_optout(motivo="numero incorreto — sem interesse").
NAO encerre antes de dar essa abertura.
```

Em seguida, adicionar (no fim do arquivo, antes do fechamento `"""`) um bloco few-shot do caminho de correção, no formato consistente do projeto:

```
<few_shot_examples>

## Exemplo — CORRECAO DE NOME: salvar nome + ponte de valor (NUNCA pitch direto)

User: "Nao"
"Johny"
Assistant: [chama salvar_nome("Johny")]
"opa, era so esse cadastro que a gente queria confirmar, obrigada"
"a gente e a torrefacao de cafe especial da Serra da Canastra, direto da fazenda pra xicara"
"cafe faz mais parte do seu dia a dia ou do seu negocio?"

Nota: o lead clicou "Nao" porque o NOME no cadastro estava errado, mas se identificou (Johny) — e a
pessoa certa. Salvou o nome e AQUECEU (Regra de Ouro 0). NAO disparou "a gente trabalha com atacado…"
(isso seria pitch frio sem ponte de valor — a falha real do lead 5519981518080).

</few_shot_examples>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_valeria_secretaria_nome_2026_06_27.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Regressão do módulo de prompts outbound**

Run: `cd backend && python -m pytest tests/ -k "secretaria or outbound or prompt" -q`
Expected: PASS (sem regressões; em caso de teste que assertava o texto antigo do bloco, atualizar para o novo contrato — registrar no relatório).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/secretaria.py backend/tests/test_valeria_secretaria_nome_2026_06_27.py
git commit -m "fix(valeria): separa correcao de nome de numero errado no secretaria outbound (sem pitch frio)"
```

---

### Task 2: Erro 2 — trava "já tocado hoje" em `schedule_followup` (cap de T1 same-day)

**Files:**
- Modify: `backend/app/follow_up/service.py` (função `schedule_followup`, ~56-124; adicionar helper `_already_touched_today`)
- Test: `backend/tests/test_followup_daily_cap_2026_06_27.py` (criar)

**Interfaces:**
- Consumes: `schedule_followup(conversation_id, lead_id, channel_id, warm=True)`; `build_touch_jobs(now, conversation_id, lead_id, channel_id, env_tag, warm=...)` (cadence.py); `get_supabase()`; `_SP_TZ` (já em service.py).
- Produces: helper `_already_touched_today(conversation_id: str, now: datetime) -> bool`; `schedule_followup` passa `effective_warm = warm and not _already_touched_today(...)` para `build_touch_jobs`.

**Contexto da falha (produção, lead Johny):** dois jobs `standard` com `sequence=1` (same-day) foram criados e enviados no MESMO dia — batch 1 (criado 09:48 → enviado 11:42) e batch 2 (criado 11:48 → enviado 14:26). Cada turno de agente re-armou um T1 same-day fresco (a idempotência cancela só os `pending`, e cria nova cadência). O fix do warm-flag (deploy 27/06) cobre o lead frio; a re-armação ainda bombardeia o lead **morno** (`warm=True`). Trava: no máximo UM toque same-day por dia por conversa.

**Design:** `_already_touched_today` consulta `follow_up_jobs` por um job `standard` já **enviado** (`status='sent'`) cuja `sent_at` cai **hoje** em `America/Sao_Paulo`. Se existir, `schedule_followup` força `warm=False` (suprime o novo T1 same-day; a cadência recriada começa no T2). Fail-open: erro de DB → `False` (não bloqueia o agendamento).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_followup_daily_cap_2026_06_27.py
"""Erro 2 (parte 2): cap de T1 same-day — um lead não recebe múltiplos toques no mesmo dia.

Produção (lead Johny): dois jobs standard seq=1 (same-day) enviados no mesmo dia porque cada
turno re-armava a cadência. A trava força warm=False se já houve toque same-day hoje.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import app.follow_up.service as svc


def _conv_exists(sb):
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
        MagicMock(data=[{"id": "conv-1"}])
    )


def test_already_touched_today_true_quando_ha_sent_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)  # 14h BRT
    sb = MagicMock()
    # query de jobs sent hoje retorna 1 linha
    (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
       .gte.return_value.lt.return_value.limit.return_value.execute.return_value) = MagicMock(
        data=[{"id": "job-sent"}]
    )
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    assert svc._already_touched_today("conv-1", now) is True


def test_schedule_followup_forca_warm_false_se_ja_tocado_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)
    captured = {}

    def fake_build(now_, conv, lead, chan, env, warm=True):
        captured["warm"] = warm
        return []

    sb = MagicMock()
    _conv_exists(sb)
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    monkeypatch.setattr(svc, "_already_touched_today", lambda c, n: True)
    monkeypatch.setattr("app.follow_up.cadence.build_touch_jobs", fake_build)

    svc.schedule_followup("conv-1", "lead-1", "chan-1", warm=True)
    assert captured["warm"] is False  # cap: já tocou hoje → suprime T1 same-day


def test_schedule_followup_preserva_warm_true_sem_toque_hoje(monkeypatch):
    now = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)
    captured = {}

    def fake_build(now_, conv, lead, chan, env, warm=True):
        captured["warm"] = warm
        return []

    sb = MagicMock()
    _conv_exists(sb)
    monkeypatch.setattr(svc, "get_supabase", lambda: sb)
    monkeypatch.setattr(svc, "_already_touched_today", lambda c, n: False)
    monkeypatch.setattr("app.follow_up.cadence.build_touch_jobs", fake_build)

    svc.schedule_followup("conv-1", "lead-1", "chan-1", warm=True)
    assert captured["warm"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_followup_daily_cap_2026_06_27.py -v`
Expected: FAIL — `AttributeError: module 'app.follow_up.service' has no attribute '_already_touched_today'`.

- [ ] **Step 3: Implement — helper + integração em `service.py`**

Adicionar o helper antes de `schedule_followup`:

```python
def _already_touched_today(conversation_id: str, now: datetime) -> bool:
    """True se esta conversa já recebeu um toque de cadência ENVIADO hoje (America/Sao_Paulo).

    Trava anti-bombardeio (Erro 2): a cadência é re-armada a cada turno do agente (idempotência
    cancela só os pending e recria), então um lead morno que responde e some várias vezes recebia
    múltiplos T1 same-day no mesmo dia (produção: lead 5519981518080, toques 11:42 e 14:26).
    Fail-open: erro de DB → False (nunca bloqueia o agendamento por falha de leitura).
    """
    try:
        local_now = now.astimezone(_SP_TZ)
        day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = day_start_local.astimezone(timezone.utc).isoformat()
        day_end = (day_start_local + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        res = (
            get_supabase().table("follow_up_jobs")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("status", "sent")
            .eq("job_type", "standard")
            .gte("sent_at", day_start)
            .lt("sent_at", day_end)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP] falha ao checar toque same-day conv=%s: %s — fail-open", conversation_id, exc
        )
        return False
```

Em `schedule_followup`, trocar a chamada a `build_touch_jobs` para usar o `effective_warm`:

```python
    # Trava de cap same-day (Erro 2): se já houve toque enviado hoje, suprime o novo T1 same-day
    # (warm efetivo = warm pedido E ainda não tocou hoje). Mantém a supressão do lead frio também.
    effective_warm = warm and not _already_touched_today(conversation_id, now)
    from app.follow_up.cadence import build_touch_jobs
    jobs = build_touch_jobs(now, conversation_id, lead_id, channel_id, _ENV_TAG, warm=effective_warm)
```

(Remover a linha antiga `jobs = build_touch_jobs(... warm=warm)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_followup_daily_cap_2026_06_27.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Regressão da suíte de follow-up**

Run: `cd backend && python -m pytest tests/ -k "followup or follow_up or cadence or schedule" -q`
Expected: PASS. Se algum teste existente de `schedule_followup` mockava `build_touch_jobs` e agora vê `_already_touched_today` chamando o DB real, ajustar o mock (patchar `_already_touched_today` para `False` no setup). Registrar no relatório.

- [ ] **Step 6: Commit**

```bash
git add backend/app/follow_up/service.py backend/tests/test_followup_daily_cap_2026_06_27.py
git commit -m "fix(followup): cap de T1 same-day (nao re-arma toque no mesmo dia) — anti-bombardeio do lead morno"
```

---

### Task 3: Erro 3 — âncora temporal no follow-up (Δt) + grounding anti-invenção

**Files:**
- Modify: `backend/app/follow_up/scheduler.py` (helper novo `_humanize_elapsed`; `_build_followup_system_prompt`; `_generate_followup_message`; select do histórico em `process_due_followups` ~557)
- Test: `backend/tests/test_followup_temporal_anchor_2026_06_27.py` (criar)

**Interfaces:**
- Consumes: `_build_followup_system_prompt(sequence, objetivo=None)`; `_generate_followup_message(history, sequence, lead_id=None, stage=None, objective_prompt=None, objetivo=None)`; `_FOLLOWUP_TZ_BR`; `_FOLLOWUP_REENGAGE_INSTRUCTION`.
- Produces:
  - `_humanize_elapsed(delta: timedelta) -> str` — "hoje mesmo, há poucos minutos" / "hoje, há ~2 horas" / "há ~3 dias".
  - `_build_followup_system_prompt(sequence, objetivo=None, last_msg_age=None)` — novo param opcional `last_msg_age: str | None`; quando presente injeta a âncora temporal + a proibição de inventar período.
  - `_generate_followup_message(..., now: datetime | None = None)` — novo param opcional `now`; computa Δt da última msg do histórico (usa `created_at`) e repassa `last_msg_age` ao system prompt.

**Contexto da falha (produção, lead Johny):** o follow-up das 11:42 disse "a gente se falou rapidinho **outro dia**" — o 1º contato foi 09:40 da MESMA manhã. O histórico é passado sem timestamps (`select("role, content")`), então o LLM, no framing de reengajamento, confabula um intervalo. A data de hoje É injetada, mas saber "hoje é 26/06" não diz quanto tempo passou desde a última troca.

**Design (segue `gemini-prompting-strategies.md` → "Add context" + cláusula de grounding):**
1. `process_due_followups`: incluir `created_at` no select do histórico e passar `now` a `_generate_followup_message`.
2. `_generate_followup_message`: da última mensagem com `created_at`, computar `now - created_at` e humanizar; repassar como `last_msg_age` ao system prompt.
3. `_build_followup_system_prompt`: injetar a âncora ("a última mensagem desta conversa foi enviada {last_msg_age}") + proibição direta de inventar períodos.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_followup_temporal_anchor_2026_06_27.py
"""Erro 3 (parte 2): âncora temporal no follow-up evita 'outro dia' alucinado.

Produção (lead Johny): follow-up disse 'a gente se falou rapidinho outro dia' sendo que o 1º
contato foi na mesma manhã. Injetamos Δt da última mensagem + proibição de inventar período.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.follow_up import scheduler
from app.follow_up.scheduler import _build_followup_system_prompt, _humanize_elapsed


def test_humanize_elapsed_horas_e_dias():
    assert "hora" in _humanize_elapsed(timedelta(hours=2))
    assert "dia" in _humanize_elapsed(timedelta(days=3))
    # poucos minutos → "hoje"
    assert "hoje" in _humanize_elapsed(timedelta(minutes=5)).lower()


def test_system_prompt_injeta_ancora_e_proibe_inventar_periodo():
    low = _build_followup_system_prompt(2, objetivo="reforco_valor", last_msg_age="hoje, há ~2 horas").lower()
    assert "hoje, há ~2 horas" in low
    # grounding: proíbe inventar período de tempo
    assert "outro dia" in low  # citado como exemplo do que NÃO dizer
    assert "invent" in low or "nao diga" in low or "não diga" in low


def test_system_prompt_sem_ancora_nao_quebra():
    # compat: sem last_msg_age, não injeta a linha de âncora
    low = _build_followup_system_prompt(2, objetivo="reforco_valor").lower()
    assert "última mensagem desta conversa foi enviada" not in low


@pytest.mark.asyncio
async def test_generate_computa_e_repassa_last_msg_age(monkeypatch):
    seen = {}

    def fake_build(sequence, objetivo=None, last_msg_age=None):
        seen["age"] = last_msg_age
        return "SYSTEM"

    monkeypatch.setattr(scheduler, "_build_followup_system_prompt", fake_build)
    monkeypatch.setattr(scheduler, "track_token_usage", lambda **k: None)

    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = "oi"
    resp.choices[0].finish_reason = "stop"
    resp.usage = None
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    monkeypatch.setattr(scheduler, "AsyncOpenAI", lambda **k: client)

    now = datetime(2026, 6, 26, 14, 47, tzinfo=timezone.utc)
    history = [{"role": "user", "content": "oi", "created_at": "2026-06-26T12:47:00+00:00"}]
    await scheduler._generate_followup_message(history, 2, objetivo="reforco_valor", now=now)
    assert seen["age"] is not None and "hora" in seen["age"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_followup_temporal_anchor_2026_06_27.py -v`
Expected: FAIL — `ImportError: cannot import name '_humanize_elapsed'`.

- [ ] **Step 3: Implement — `scheduler.py`**

(a) Adicionar helper perto do topo dos utilitários do follow-up (após `_normalize_literal_newlines`):

```python
def _humanize_elapsed(delta: timedelta) -> str:
    """Humaniza Δt desde a última mensagem, para ancorar o follow-up no tempo real (anti-'outro dia')."""
    secs = max(0, int(delta.total_seconds()))
    if secs < 90 * 60:
        return "hoje mesmo, há pouco tempo (menos de 2 horas)"
    hours = secs // 3600
    if hours < 24:
        return f"hoje, há ~{hours} hora{'s' if hours != 1 else ''}"
    days = secs // 86400
    return f"há ~{days} dia{'s' if days != 1 else ''}"
```

(b) Estender a proibição no `_FOLLOWUP_REENGAGE_INSTRUCTION` — adicionar à seção "## 3. Proibições" a linha:

```
- PROIBIDO inventar período de tempo. NAO diga 'outro dia', 'semana passada', 'mes passado' ou
  qualquer intervalo que voce nao tenha certeza. Use APENAS o tempo informado no contexto temporal
  abaixo (se houver). Na duvida, nao cite quando foi a ultima conversa.
```

(c) `_build_followup_system_prompt` — novo param e injeção da âncora:

```python
def _build_followup_system_prompt(
    sequence: int, objetivo: str | None = None, last_msg_age: str | None = None
) -> str:
    is_last_attempt = objetivo == "ultima_chamada"
    seq_tone = (
        "esta é a última tentativa antes da janela de atendimento expirar: seja mais direta, "
        "crie senso de oportunidade, mas sem ser agressiva"
        if is_last_attempt
        else
        "esta é uma retomada de reengajamento: leve, curiosa e natural, sem pressionar — "
        "retome pelo assunto que ficou em aberto e demonstre interesse genuíno"
    )
    persona = build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(_FOLLOWUP_TZ_BR))
    temporal = (
        f"\nContexto temporal (GROUNDING): a última mensagem desta conversa foi enviada {last_msg_age}. "
        "Use exatamente essa referência — não invente outro intervalo."
        if last_msg_age else ""
    )
    return f"{persona}\n\n{_FOLLOWUP_REENGAGE_INSTRUCTION}\nTom desta tentativa: {seq_tone}{temporal}"
```

(d) `_generate_followup_message` — novo param `now`, computa Δt e repassa:

```python
async def _generate_followup_message(
    history: list[dict],
    sequence: int,
    lead_id: str | None = None,
    stage: str | None = None,
    objective_prompt: str | None = None,
    objetivo: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    ...
    from app.agent.orchestrator import _gemini_thinking_off
    ...
    # Âncora temporal (Erro 3): Δt da última mensagem do histórico, para o LLM não inventar 'outro dia'.
    last_msg_age = None
    if now is not None and history:
        last_created = history[-1].get("created_at")
        if last_created:
            try:
                ts = datetime.fromisoformat(str(last_created).replace("Z", "+00:00"))
                last_msg_age = _humanize_elapsed(now - ts)
            except Exception:
                last_msg_age = None

    system_prompt = _build_followup_system_prompt(sequence, objetivo=objetivo, last_msg_age=last_msg_age)
    if objective_prompt:
        system_prompt = f"{system_prompt}\n\nOBJETIVO DESTE TOQUE (Next Best Action): {objective_prompt}"
    ...
```

(e) `process_due_followups` — incluir `created_at` no select e passar `now`:

```python
            history_result = (
                sb.table("messages")
                .select("role, content, created_at")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            history = list(reversed(history_result.data or []))
            history = [m for m in history if m.get("role") and m.get("content")]
            objective_prompt = (job.get("metadata") or {}).get("objective_prompt")
            objetivo = (job.get("metadata") or {}).get("objetivo")
            message, finish_reason = await _generate_followup_message(
                history, sequence, lead_id=job["lead_id"], stage=conversation.get("stage"),
                objective_prompt=objective_prompt, objetivo=objetivo, now=now,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_followup_temporal_anchor_2026_06_27.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Regressão (tom + follow-up + persona)**

Run: `cd backend && python -m pytest tests/ -k "followup or follow_up or tone or perfeicao" -q`
Expected: PASS. O teste existente `test_followup_tone_cold_start_2026_06_27.py` e `test_outbound_perfeicao.py` (que chamam `_build_followup_system_prompt`) continuam verdes pois `last_msg_age` é opcional. Se algum chamava `_generate_followup_message` sem `now`, o param é opcional (default None) — sem quebra.

- [ ] **Step 6: Commit**

```bash
git add backend/app/follow_up/scheduler.py backend/tests/test_followup_temporal_anchor_2026_06_27.py
git commit -m "fix(followup): injeta ancora temporal (Δt) no historico + grounding anti-'outro dia'"
```

---

### Task 4: Verificação final de regressão

**Files:** nenhum (só execução).

- [ ] **Step 1: Suíte completa do backend**

Run: `cd backend && python -m pytest -q`
Expected: PASS (0 failures). Anotar contagem `passed/skipped`.

- [ ] **Step 2: Conferir os 3 fixes coexistindo**

Run: `cd backend && python -m pytest tests/test_valeria_secretaria_nome_2026_06_27.py tests/test_followup_daily_cap_2026_06_27.py tests/test_followup_temporal_anchor_2026_06_27.py -v`
Expected: PASS (todos).

- [ ] **Step 3: Review da branch (requesting-code-review)**

Usar `superpowers:requesting-code-review` sobre o diff completo da branch. Triar findings Critical/Important antes de declarar concluído.

---

## Self-Review (autor do plano)

**Spec coverage:**
- Erro 1 (separar correção de nome de número errado, salvar + ponte/WIIFM, sem oferta direta) → Task 1. ✓
- Erro 2 (trava cap diário / "já tocado hoje" no processor/cadence) → Task 2 (em `service.py`, o seam de I/O correto; `cadence.py` é função pura sem I/O, por isso a trava fica em `schedule_followup`). ✓
- Erro 3 (injeção de timestamps/Δt no histórico + grounding anti-invenção) → Task 3. ✓
- TDD/branch nova/SDD → header + Global Constraints + Task 4. ✓
- gemini-prompting-strategies em prompts → Global Constraints + Tasks 1 e 3. ✓

**Placeholder scan:** sem TODOs/"handle edge cases" — todo step tem código/comando concreto. ✓

**Type consistency:** `_already_touched_today(conversation_id, now) -> bool`, `effective_warm`, `_humanize_elapsed(delta) -> str`, `_build_followup_system_prompt(sequence, objetivo=None, last_msg_age=None)`, `_generate_followup_message(..., now=None)` — nomes e assinaturas consistentes entre tasks. ✓

**Nota de escopo:** Erro 2 fica em `service.py` (não em `cadence.py`) porque a decisão precisa de I/O; o user citou "processor.py ou cadence.py" — `schedule_followup` é o ponto idempotente que de fato re-arma a cadência, então é o local correto e mínimo.

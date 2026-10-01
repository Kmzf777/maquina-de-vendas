# Follow-up × fluxo de botões — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O motor de follow-up para de mandar mensagem de LLM para lead atendido por fluxo de botões — sem desligar os caminhos que precisam continuar.

**Architecture:** Um motivo de parada novo (`"fluxo_de_botoes"`) no backstop único que já existe (`_lead_stop_reason`), decidido por `runner.fluxo_da_conversa` — a função que já é a dona dessa regra. As colunas do perfil chegam alargando o `select` do job, que já faz o join: zero consulta extra por job.

**Tech Stack:** Python 3 / FastAPI / Supabase, pytest (`asyncio_mode = auto`).

**Spec:** `docs/superpowers/specs/2026-10-01-followup-x-fluxo-de-botoes-design.md` — leia antes da Task 1.

---

## Ondas

| Onda | Tasks | Arquivos |
|---|---|---|
| 1 | 1, 2 | `follow_up/service.py` + `follow_up/scheduler.py` · `frontend/.../valeria-flow-modal.tsx` |
| 2 | 3 | teste fictício ponta a ponta |

Task 1 e Task 2 não se cruzam (backend × frontend). Task 3 depende da 1.

## Regras de execução com subagentes

- **Subagente NUNCA toca em git.** Proibido: `add`, `commit`, `checkout`, `restore`, `reset`, `stash`, `rm`, `clean`, `switch`, `branch`. O index é recurso compartilhado.
- **Não rode a suíte inteira** (`pytest tests/`, 8 min). Rode o conjunto escopado; o orquestrador roda a suíte completa no fechamento.
- **Se o plano estiver errado, PARE e reporte.** Nove defeitos de plano foram pegos assim nesta base de código, incluindo um que deixaria toda chamada do modal em 401 em produção.
- Armadilhas desta base: escape `\n` virando newline real dentro de string literal (rode `ast.parse`); acento persistido como `?` (decodifique em UTF-8 estrito); e uma guarda que proíbe marcador de modelo OpenAI em `app/` (rode `tests/test_no_openai_provider_2026_07_02.py`).

---

## Task 1: O motivo de parada novo

**Files:**
- Modify: `backend/app/follow_up/service.py` (o `select` de `get_due_followups`, ~linha 731)
- Modify: `backend/app/follow_up/scheduler.py` (`_lead_stop_reason` ~959, `_stop_reason_applies` ~1024, o call site ~687)
- Test: `backend/tests/test_followup_x_botoes_2026_10_01.py`

**Leia antes:** `scheduler.py:959-1047` inteiro (o backstop e a tabela de isenção existentes, com os comentários que registram os casos Wilson Demuth e 5511910402026) e `button_flow/runner.py::fluxo_da_conversa`.

- [ ] **Step 1: Escreva o teste que falha**

```python
"""O follow-up para de falar por cima do fluxo de botões.

O motor decidia por `ai_enabled` e canal humano, e não sabia que fluxos de botões
existem. Um lead que para no meio da árvore tem `ai_enabled=True` — nada o
silenciou — então o `ai_reengage` disparava uma mensagem de LLM por cima de uma
conversa de botões, e a resposta dele caía no motor de botões como texto livre.
"""
import pytest

from app.follow_up import scheduler as S

FLUXO = "valeria_botoes_v1"
CONV_BOTOES = {"id": "c1", "agent_profile_id": "p-botoes"}
CONV_LLM = {"id": "c2", "agent_profile_id": "p-llm"}
CANAL = {"id": "ch1", "mode": "ai", "agent_profiles": {"kind": "llm", "flow_id": None}}
LEAD = {"id": "l1", "ai_enabled": True, "metadata": {}}


@pytest.fixture(autouse=True)
def _sem_blacklist(monkeypatch):
    monkeypatch.setattr(S, "is_lead_blacklisted", lambda _id: False)


@pytest.fixture
def botoes_ligado(monkeypatch):
    """Perfil da conversa resolve para o fluxo de botões da ValerIA."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    from app.button_flow import runner as R
    monkeypatch.setattr(R, "get_agent_profile", lambda pid: (
        {"kind": "button_flow", "flow_id": FLUXO} if pid == "p-botoes"
        else {"kind": "llm", "flow_id": None}))
    R.limpar_cache_de_perfis()


# ── O motivo ────────────────────────────────────────────────────────────────
def test_conversa_de_botoes_vira_motivo_de_parada(botoes_ligado):
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) == "fluxo_de_botoes"


def test_conversa_de_llm_no_mesmo_canal_nao_para(botoes_ligado):
    """A conversa vence o canal: lead que o disparo apontou para a LLM segue recebendo."""
    assert S._lead_stop_reason(LEAD, CONV_LLM, CANAL) is None


def test_sem_conversa_nem_canal_o_motivo_nao_dispara(botoes_ligado):
    """Chamador antigo: comportamento byte-idêntico ao de hoje."""
    assert S._lead_stop_reason(LEAD) is None


def test_com_o_fluxo_desligado_nao_dispara_e_nao_consulta_o_banco(monkeypatch):
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    from app.button_flow import runner as R
    def explode(_pid):
        raise AssertionError("consultou agent_profiles com todos os fluxos desligados")
    monkeypatch.setattr(R, "get_agent_profile", explode)
    R.limpar_cache_de_perfis()
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) is None


def test_erro_ao_resolver_o_perfil_e_fail_open(monkeypatch, botoes_ligado):
    from app.button_flow import runner as R
    def explode(_pid):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(R, "get_agent_profile", explode)
    R.limpar_cache_de_perfis()
    assert S._lead_stop_reason(LEAD, CONV_BOTOES, CANAL) is None


# ── Precedência: o analytics não pode perder informação ────────────────────
def test_optout_vence_fluxo_de_botoes(botoes_ligado):
    lead = {**LEAD, "opt_out": True}
    assert S._lead_stop_reason(lead, CONV_BOTOES, CANAL) == "opt_out"


def test_fluxo_de_botoes_vence_ai_disabled(botoes_ligado):
    """`ai_disabled` é consequência; `fluxo_de_botoes` é a causa útil no analytics."""
    lead = {**LEAD, "ai_enabled": False}
    assert S._lead_stop_reason(lead, CONV_BOTOES, CANAL) == "fluxo_de_botoes"


# ── Quem é bloqueado e quem é isento ──────────────────────────────────────
@pytest.mark.parametrize("job_type", ["standard", "ai_reengage", "ai_scheduled_return"])
def test_os_tipos_que_falam_com_o_lead_por_llm_sao_bloqueados(job_type):
    assert S._stop_reason_applies("fluxo_de_botoes", job_type) is True


def test_handoff_rescue_e_isento():
    """Notifica o VENDEDOR por template, não o lead. É o anteparo de quem foi
    transbordado e ninguém pegou (caso Wilson Demuth, >21h no vácuo)."""
    assert S._stop_reason_applies("fluxo_de_botoes", "handoff_rescue") is False


def test_lp_welcome_e_isento():
    """Lead de LP ainda NÃO mandou mensagem — não há estado de fluxo. Bloquear
    faria nenhum lead de landing page ser recebido."""
    assert S._stop_reason_applies("fluxo_de_botoes", "lp_welcome") is False


def test_tipo_do_joao_e_isento():
    tipo = next(t for t in ("joao_novo_1", "joao_em_conversa_1") if S._is_joao_job_type(t))
    assert S._stop_reason_applies("fluxo_de_botoes", tipo) is False


def test_as_isencoes_de_ai_disabled_nao_mudaram():
    """Regressão: a tabela existente continua valendo."""
    assert S._stop_reason_applies("ai_disabled", "handoff_rescue") is False
    assert S._stop_reason_applies("ai_disabled", "standard") is True
    assert S._stop_reason_applies("opt_out", "handoff_rescue") is True


# ── O select do job tem de trazer as colunas ──────────────────────────────
def test_o_select_do_job_traz_o_perfil():
    """Sem estas colunas o motivo nunca dispara, e o teste acima passaria mentindo."""
    import inspect
    from app.follow_up import service
    fonte = inspect.getsource(service.get_due_followups)
    assert "agent_profile_id" in fonte
    assert "agent_profiles(" in fonte
```

**Se `_is_joao_job_type` não aceitar nenhum dos dois nomes do teste, PARE e reporte** — leia a função e use um prefixo que ela reconheça de verdade.

- [ ] **Step 2: Rode e confirme que falha**

`cd backend && python -m pytest tests/test_followup_x_botoes_2026_10_01.py -v`
Esperado: `TypeError` (`_lead_stop_reason` não aceita 3 argumentos) e os de isenção devolvendo `True` por o motivo não existir na tabela.

- [ ] **Step 3: Implemente**

Em `service.py`, alargue o `select` de `get_due_followups` sem tirar nada:

```python
                "leads!inner(id, phone, name, last_customer_message_at, wa_id), "
                "channels!inner(id, name, provider, provider_config, mode, "
                "agent_profile_id, agent_profiles(kind, flow_id)), "
                "conversations!inner(id, stage, followup_enabled, "
                "last_customer_message_at, agent_profile_id)"
```

Em `scheduler.py`, `_lead_stop_reason` ganha os dois parâmetros opcionais e o motivo novo,
**depois** de `wrong_number` e **antes** de `is_lead_blacklisted`:

```python
def _lead_stop_reason(lead: dict | None, conversation: dict | None = None,
                      channel: dict | None = None) -> str | None:
```

```python
    # ANTES de `is_lead_blacklisted` e de `ai_disabled`, e a ordem tem duas razões.
    # Contra a blacklist: esta checagem é mais barata (o cache de perfil de 300s de
    # `runner._perfil_cache`, e nem isso quando todos os fluxos estão desligados).
    # Contra `ai_disabled`: um lead em fluxo de botões costuma ter `ai_enabled=False`
    # junto (o handoff e o T_HUMANO desligam), e gravar `cancel_reason="ai_disabled"`
    # perderia no analytics a informação que importa — o lead não parou, ele está
    # sendo atendido por OUTRO motor.
    #
    # `conversation`/`channel` são opcionais porque o backstop é chamado de um ponto
    # que não os tinha. Sem eles o motivo não dispara: fail-open, igual ao resto.
    if conversation is not None or channel is not None:
        try:
            if fluxo_da_conversa(conversation or {}, channel or {}):
                return "fluxo_de_botoes"
        except Exception as exc:
            logger.warning(
                "[FOLLOWUP] falha ao resolver o fluxo da conversa — seguindo: %s", exc)
```

Em `_stop_reason_applies`, declare a isenção. **Não** reuse `_STOP_REASON_EXEMPT_JOB_TYPES`
para os tipos do João: aquele casamento é por prefixo e já tem o seu próprio `if`.

```python
_STOP_REASON_EXEMPT_JOB_TYPES: dict[str, frozenset[str]] = {
    "ai_disabled": frozenset({"handoff_rescue"}),
    # `handoff_rescue` notifica o VENDEDOR por template, não o lead: é o anteparo de
    # quem o fluxo acabou de entregar e ninguém pegou. `lp_welcome` é o primeiro
    # contato de um lead de landing page que AINDA NÃO mandou mensagem — não há
    # estado de fluxo, e bloquear faria nenhum lead de LP ser recebido.
    "fluxo_de_botoes": frozenset({"handoff_rescue", "lp_welcome"}),
}
```

E o `if` dos tipos do João passa a valer para os dois motivos:

```python
    if reason in ("ai_disabled", "fluxo_de_botoes") and _is_joao_job_type(job_type):
        return False
```

No call site (`:687`), passe o que o job já traz:

```python
                stop_reason = _lead_stop_reason(
                    _fetch_lead_for_backstop(stop_lead_id),
                    job.get("conversations"),
                    job.get("channels"),
                )
```

- [ ] **Step 4: Rode o conjunto escopado**

```
cd backend && python -m pytest tests/test_followup_x_botoes_2026_10_01.py tests/test_agendador_joao_2026_09_18.py tests/test_valeria_gate_2026_09_29.py tests/test_valeria_processor_2026_09_30.py tests/test_button_flow_runner_2026_09_09.py -q -k "not integration"
```
Mais a varredura do follow-up, que é onde a regressão apareceria:
```
cd backend && python -m pytest tests/ -q -k "followup or follow_up or agendador or reengage"
```
E a guarda de OpenAI: `python -m pytest tests/test_no_openai_provider_2026_07_02.py -q`

- [ ] **Step 5: Reporte ao orquestrador.** NÃO commite.

---

## Task 2: Trocar de aba não apaga mais a edição

**Files:**
- Modify: `frontend/src/components/campaigns/valeria-flow-modal.tsx`
- Modify: `frontend/src/components/campaigns/valeria-flow-modal.test.tsx`

**INVOQUE A SKILL `frontend-design` ANTES** de tocar em componente — instrução registrada do dono.

O editor guarda o rascunho em estado local e o shell renderiza **um painel por vez**, então
clicar em "Onde está ativo" **desmonta o editor e perde o texto digitado** — sem aviso,
mesmo com a aba mostrando "· não salvo". Só passou a ser alcançável quando o editor real
montou.

Escolha **uma** das duas e justifique no código:
1. Manter o editor montado e apenas oculto (`hidden`), preservando o estado. O painel de
   canais segue montando só quando aberto, para não disparar o `GET /channels` de uma aba
   que ninguém abriu.
2. Avisar antes de trocar de aba quando há rascunho, com confirmação **no painel** (não
   `window.confirm`, que não funciona neste ambiente).

A (1) é mais simples e não inventa diálogo; a (2) é mais explícita. Decida lendo o shell.

Teste: digitar no editor, trocar de aba, voltar, e o texto **continua lá** (ou o aviso
aparece, conforme a escolha). Componente precisa do docblock
`/** @vitest-environment jsdom */` na primeira linha — `vitest.config.ts` põe
`environment: "node"` global de propósito.

- [ ] Rode `cd frontend && npx vitest run src/components/campaigns/` e `npx tsc --noEmit`.
- [ ] Reporte. NÃO commite.

---

## Task 3: Teste fictício ponta a ponta

**Files:**
- Create: `backend/tests/test_followup_x_botoes_e2e_2026_10_01.py`

Depende da Task 1. Simula conversa completa com dados fictícios, exercitando o que teste
unitário não cobre: a **ordem** entre os dois motores.

Dublê no provedor de WhatsApp e no LLM. **Qualquer chamada real a um deles falha o teste** —
asserção explícita, não confiança.

Cenários:

1. Lead fictício entra no fluxo, recebe a tela de entrada, toca "Pro meu negócio", recebe
   `N1` e **para**. Um job `ai_reengage` vencido para esse lead → **cancelado** com
   `cancel_reason="fluxo_de_botoes"`, zero chamada de LLM, zero envio.
2. O mesmo lead é transbordado (`T_HANDOFF`) → um `handoff_rescue` vencido **dispara**.
3. Lead de LP no mesmo canal → `lp_welcome` **dispara**.
4. Lead da ValerIA LLM no mesmo canal (conversa apontada para o perfil LLM) →
   `ai_reengage` **dispara** normalmente.
5. Com `VALERIA_BOTOES_ENABLED` ausente → tudo dispara como antes (o estado de produção
   de hoje, antes de alguém ligar a chave).

- [ ] Rode o arquivo novo mais o da Task 1. Reporte. NÃO commite.

---

## Verificação final (orquestrador)

- [ ] `cd backend && python -m pytest tests/ -q` — baseline a bater: a contagem de `origin/master` mais os testes novos
- [ ] `cd frontend && npx vitest run` e `npx tsc --noEmit`
- [ ] `git status --short` e `git log --oneline origin/master..HEAD`
- [ ] `git pull origin master` e rodar as duas suítes **depois** do merge
- [ ] Push só se tudo verde

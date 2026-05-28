# Outbound Rehearsal Setup — Valéria Outbound

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Montar a infraestrutura completa de testes (Rehearsal) para validar a Valéria Outbound — sem executar nenhum teste ainda.

**Architecture:** Novo script `outbound_rehearsal_runner.py` + `outbound_archetypes.py` ao lado dos existentes em `backend/scripts/`, reutilizando toda a infra de suporte (gemini_actor, verifier, supabase_io, logger). O timer de 15 min (handoff rescue) é desabilitado via guard no env `REHEARSAL_MODE=true`. A execução paralela dos 4 leads é construída mas não chamada.

**Tech Stack:** Python 3.11+, asyncio, httpx, Supabase (supabase-py), Gemini API (google-generativeai), Meta Cloud API webhook format

---

## Mapa de Arquivos

| Ação | Arquivo | Responsabilidade |
|------|---------|-----------------|
| **Modify** | `backend/app/follow_up/service.py` | Guard REHEARSAL_MODE em `schedule_handoff_rescue` |
| **Create** | `backend/scripts/rehearsal/outbound_archetypes.py` | 4 archetypes O1–O4 para fluxo outbound |
| **Create** | `backend/scripts/outbound_rehearsal_runner.py` | Runner principal: seed, payload builder, loop, gather |
| **Create** | `backend/tests/test_outbound_archetypes.py` | Testes unitários dos archetypes outbound |
| **Create** | `backend/tests/test_outbound_rehearsal_runner.py` | Testes do builder de payload e seed |

---

## Task 1: Guard REHEARSAL_MODE no timer de 15 min

**Files:**
- Modify: `backend/app/follow_up/service.py:167-204`
- Test: `backend/tests/test_handoff_rescue.py` (adicionar caso)

### Contexto
`schedule_handoff_rescue` em `service.py:167` agenda um job `handoff_rescue` que dispara uma mensagem para o João 15 minutos após um handoff. Durante o Rehearsal, esse timer não deve ser agendado.

- [ ] **Step 1: Escrever o teste que falha**

Em `backend/tests/test_handoff_rescue.py`, adicionar ao final do arquivo:

```python
def test_schedule_handoff_rescue_skipped_in_rehearsal_mode(monkeypatch):
    """REHEARSAL_MODE=true deve impedir que o rescue job seja inserido."""
    import os
    from app.follow_up.service import schedule_handoff_rescue

    monkeypatch.setenv("REHEARSAL_MODE", "true")
    mock_sb = MagicMock()

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb):
        schedule_handoff_rescue(
            lead_id="lead-r",
            lead_phone="5511000000001",
            conversation_id="conv-r",
            channel_id="chan-r",
        )

    # Insert não deve ter sido chamado
    mock_sb.table.return_value.insert.assert_not_called()
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
cd backend && python -m pytest tests/test_handoff_rescue.py::test_schedule_handoff_rescue_skipped_in_rehearsal_mode -v
```

Saída esperada: `FAILED` — a função ainda insere mesmo com REHEARSAL_MODE.

- [ ] **Step 3: Implementar o guard**

Em `backend/app/follow_up/service.py`, adicionar as duas primeiras linhas do corpo de `schedule_handoff_rescue` (após a docstring, antes do `sb = get_supabase()`):

Arquivo atual (linhas 167-176):
```python
def schedule_handoff_rescue(
    lead_id: str,
    lead_phone: str,
    conversation_id: str,
    channel_id: str,
    delay_minutes: int = 15,
) -> None:
    """Agenda um job de resgate de handoff (job_type='handoff_rescue') para fire em delay_minutes."""
    sb = get_supabase()
```

Substituir por:
```python
def schedule_handoff_rescue(
    lead_id: str,
    lead_phone: str,
    conversation_id: str,
    channel_id: str,
    delay_minutes: int = 15,
) -> None:
    """Agenda um job de resgate de handoff (job_type='handoff_rescue') para fire em delay_minutes."""
    import os
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[HANDOFF_RESCUE] REHEARSAL_MODE ativo — rescue ignorado")
        return
    sb = get_supabase()
```

- [ ] **Step 4: Rodar o teste para confirmar que passa**

```bash
cd backend && python -m pytest tests/test_handoff_rescue.py -v
```

Saída esperada: todos os testes `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/service.py backend/tests/test_handoff_rescue.py
git commit -m "fix(rehearsal): desabilitar handoff rescue timer quando REHEARSAL_MODE=true"
```

---

## Task 2: Archetypes Outbound (O1–O4)

**Files:**
- Create: `backend/scripts/rehearsal/outbound_archetypes.py`
- Test: `backend/tests/test_outbound_archetypes.py`

### Contexto
O fluxo outbound começa com um template enviado pela Valéria (não pelo lead). A primeira interação do lead é **uma resposta ao template** — pode ser um botão quick_reply ou texto livre. Os archetypes definem quem é cada lead e como ele reage após receber esse template.

O template `utilidade_22_04_2026_16_40` tem texto:
> "Olá, tudo bem? Aqui é a Valéria, da Café Canastra. Estamos atualizando nossos registros de contato e queria confirmar rapidinho com você. Falo com João neste número? Valéria | Café Canastra"

Botões: "Sim", "Não", "Parar mensagens"

**O1**: Lead confirma ser o João ("Sim") e é qualificado.
**O2**: Lead nega ser o João ("Não") mas demonstra interesse no produto.
**O3**: Lead clica "Parar mensagens" — Valéria deve encerrar com elegância.
**O4**: Lead ignora botões, responde texto ambíguo — Valéria deve interpretar e conduzir.

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_outbound_archetypes.py`:

```python
"""Testes unitários para os archetypes outbound O1-O4."""
import pytest
from scripts.rehearsal.outbound_archetypes import (
    ALL_OUTBOUND_ARCHETYPES,
    OUTBOUND_ARCHETYPES,
    O1, O2, O3, O4,
)


def test_all_archetypes_present():
    assert len(ALL_OUTBOUND_ARCHETYPES) == 4
    ids = [a.id for a in ALL_OUTBOUND_ARCHETYPES]
    assert ids == ["O1", "O2", "O3", "O4"]


def test_archetype_dict_keys():
    assert set(OUTBOUND_ARCHETYPES.keys()) == {
        "O1-confirmacao-qualificado",
        "O2-negacao-potencial",
        "O3-opt-out",
        "O4-textual-ambiguo",
    }


def test_first_messages_are_button_replies_or_text():
    """O1/O2/O3 iniciam com dict (button_reply), O4 com string."""
    assert isinstance(O1.first_message, dict)
    assert O1.first_message["type"] == "button_reply"
    assert O1.first_message["button_id"] == "sim"

    assert isinstance(O2.first_message, dict)
    assert O2.first_message["button_id"] == "nao"

    assert isinstance(O3.first_message, dict)
    assert O3.first_message["button_id"] == "parar_mensagens"

    assert isinstance(O4.first_message, str)


def test_hard_checks_defined():
    for arch in ALL_OUTBOUND_ARCHETYPES:
        assert len(arch.hard_checks) >= 1, f"{arch.id} sem hard_checks"


def test_forbids_defined():
    for arch in ALL_OUTBOUND_ARCHETYPES:
        assert len(arch.forbids) >= 1, f"{arch.id} sem forbids"
```

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
cd backend && python -m pytest tests/test_outbound_archetypes.py -v
```

Saída esperada: `ModuleNotFoundError` ou `ImportError` — arquivo não existe.

- [ ] **Step 3: Criar `outbound_archetypes.py`**

Criar `backend/scripts/rehearsal/outbound_archetypes.py`:

```python
"""4 archetypes outbound para testar a Valéria Outbound (O1-O4).

O fluxo difere dos archetypes inbound (T1-T6): o lead responde a um
template enviado pela Valéria. first_message pode ser um dict com
type='button_reply' (para simular quick reply) ou uma str (texto livre).
"""
from dataclasses import dataclass, field
from typing import Callable, Union

from scripts.rehearsal.archetypes import (
    Archetype,
    has_tool_call,
    reached_stage,
    transcript_matches,
    visited_multiple_stages,
    min_turns,
)
from scripts.rehearsal.forbids import UNIVERSAL_FORBIDS


@dataclass
class OutboundArchetype(Archetype):
    """Estende Archetype para suportar first_message como dict (button_reply) ou str."""
    first_message: Union[dict, str] = ""


# ─── O1: Confirmação-Qualificado ────────────────────────────────────────────

_O1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: João Pereira, dono de uma cafeteria em Belo Horizonte.
Recebeu uma mensagem da Valéria perguntando se fala com João — e clicou "Sim".
Tom: receptivo, curiosamente interessado em café de qualidade, direto.
Comportamento:
- Confirma que é o João.
- Menciona que tem uma cafeteria e serve café especial.
- Pergunta o que a Café Canastra oferece para cafeterias.
- Se a Valéria mencionar atacado ou parceria, fica animado e quer saber mais sobre volumes e preços.
- Está disposto a fazer uma primeira compra para testar.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O1 = OutboundArchetype(
    id="O1",
    slug="confirmacao-qualificado",
    persona_prompt=_O1_PERSONA,
    first_message={"type": "button_reply", "button_id": "sim", "button_title": "Sim"},
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("encaminhar_humano"),
        min_turns(3),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O2: Negação-Potencial ──────────────────────────────────────────────────

_O2_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: Maria Silva, que atendeu o celular que pertencia ao João (marido/sócio que vendeu o número).
Clicou "Não" porque de fato não é o João.
Tom: levemente confuso no início, mas curioso ao ouvir falar de café.
Comportamento:
- Explica que não é o João, que esse número era do marido/sócio.
- Pergunta o que é a Café Canastra por curiosidade.
- Se a Valéria apresentar o produto, demonstra interesse pessoal (gosta de café).
- Perguntas curtas: "Vocês entregam em casa?", "É café especial mesmo?".
- Não está no perfil B2B mas pode virar consumidor final.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O2 = OutboundArchetype(
    id="O2",
    slug="negacao-potencial",
    persona_prompt=_O2_PERSONA,
    first_message={"type": "button_reply", "button_id": "nao", "button_title": "Não"},
    hard_checks=[
        visited_multiple_stages(2),
        transcript_matches(
            r"(consumo|loja|site|link|cupom|ESPECIAL10)",
            "Valeria redirecionou para canal correto ou loja",
        ),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O3: Opt-Out ────────────────────────────────────────────────────────────

_O3_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: pessoa que não quer receber mensagens comerciais. Clicou "Parar mensagens".
Tom: seco, sem hostilidade mas definitivo.
Comportamento:
- Se a Valéria mandar mais alguma mensagem após o opt-out, responde "já pedi pra parar".
- Não demonstra interesse em nenhum produto.
- Aceita um pedido de desculpas simples e encerra.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O3 = OutboundArchetype(
    id="O3",
    slug="opt-out",
    persona_prompt=_O3_PERSONA,
    first_message={"type": "button_reply", "button_id": "parar_mensagens", "button_title": "Parar mensagens"},
    hard_checks=[
        transcript_matches(
            r"(desculp|lament|remov|nao\s+enviar|encerr|entendid)",
            "Valeria reconheceu opt-out e encerrou com elegancia",
        ),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O4: Textual-Ambíguo ────────────────────────────────────────────────────

_O4_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: Carlos, empresário que ignorou os botões e respondeu com texto confuso.
Tom: apressado, escreve de forma telegráfica, mistura perguntas.
Comportamento:
- Primeira mensagem: texto curto e ambíguo (ex: "oi quem é?? café?").
- Se a Valéria se apresentar, pergunta confusamente se é sobre pedido antigo ou novo contato.
- Após a Valéria esclarecer, demonstra interesse em comprar café para o escritório.
- Usa abreviações e não usa pontuação.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O4 = OutboundArchetype(
    id="O4",
    slug="textual-ambiguo",
    persona_prompt=_O4_PERSONA,
    first_message="oi quem é?? café??",
    hard_checks=[
        visited_multiple_stages(2),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── Exports ─────────────────────────────────────────────────────────────────

ALL_OUTBOUND_ARCHETYPES = [O1, O2, O3, O4]

OUTBOUND_ARCHETYPES = {
    "O1-confirmacao-qualificado": O1,
    "O2-negacao-potencial": O2,
    "O3-opt-out": O3,
    "O4-textual-ambiguo": O4,
}
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

```bash
cd backend && python -m pytest tests/test_outbound_archetypes.py -v
```

Saída esperada: todos os 5 testes `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rehearsal/outbound_archetypes.py backend/tests/test_outbound_archetypes.py
git commit -m "feat(rehearsal): adicionar archetypes outbound O1-O4"
```

---

## Task 3: Builder de Payload e Seed de Lead

**Files:**
- Create: `backend/scripts/outbound_rehearsal_runner.py` (parcial — funções auxiliares)
- Test: `backend/tests/test_outbound_rehearsal_runner.py`

### Contexto
O runner precisa de dois builders:
1. `_build_button_reply_payload(phone, button_id, button_title)` — monta payload Meta webhook para interactive/button_reply
2. `_build_text_payload(phone, text)` — idêntico ao `_build_meta_payload` do runner existente
3. `_build_first_message_payload(phone, first_message)` — dispatcher que escolhe qual builder usar

O seed consiste em: wipe do lead → wipe do buffer Redis → a Valéria cria o lead naturalmente quando recebe o primeiro webhook.

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_outbound_rehearsal_runner.py`:

```python
"""Testes unitários para payload builders do outbound rehearsal runner."""
import pytest
import sys
from pathlib import Path

# Garante que o módulo scripts/ é importável sem rodar main()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_build_button_reply_payload_structure():
    from scripts.outbound_rehearsal_runner import _build_button_reply_payload

    phone = "5511900000001"
    payload = _build_button_reply_payload(phone, "sim", "Sim")

    entry = payload["entry"][0]
    change = entry["changes"][0]["value"]
    msg = change["messages"][0]

    assert payload["object"] == "whatsapp_business_account"
    assert change["contacts"][0]["wa_id"] == phone
    assert msg["from"] == phone
    assert msg["type"] == "interactive"
    assert msg["interactive"]["type"] == "button_reply"
    assert msg["interactive"]["button_reply"]["id"] == "sim"
    assert msg["interactive"]["button_reply"]["title"] == "Sim"


def test_build_text_payload_structure():
    from scripts.outbound_rehearsal_runner import _build_text_payload

    phone = "5511900000002"
    payload = _build_text_payload(phone, "oi quem é?? café??")

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "text"
    assert msg["text"]["body"] == "oi quem é?? café??"


def test_build_first_message_payload_button():
    from scripts.outbound_rehearsal_runner import _build_first_message_payload

    phone = "5511900000003"
    first_message = {"type": "button_reply", "button_id": "nao", "button_title": "Não"}
    payload = _build_first_message_payload(phone, first_message)

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "interactive"
    assert msg["interactive"]["button_reply"]["id"] == "nao"


def test_build_first_message_payload_text():
    from scripts.outbound_rehearsal_runner import _build_first_message_payload

    phone = "5511900000004"
    payload = _build_first_message_payload(phone, "oi quem é??")

    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    assert msg["type"] == "text"
    assert msg["text"]["body"] == "oi quem é??"


def test_build_outbound_template_payload():
    """Verifica estrutura do payload do template de disparo inicial."""
    from scripts.outbound_rehearsal_runner import build_outbound_template_payload

    phone = "5511900000005"
    payload = build_outbound_template_payload(phone)

    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == phone
    assert payload["type"] == "template"
    tmpl = payload["template"]
    assert tmpl["name"] == "utilidade_22_04_2026_16_40"
    assert tmpl["language"]["code"] == "en"

    # Verifica que os 3 botões estão no components
    components = tmpl.get("components", [])
    button_component = next((c for c in components if c["type"] == "button"), None)
    assert button_component is not None, "Nenhum component de botão encontrado"
    buttons = button_component.get("buttons", [])
    assert len(buttons) == 3
    titles = [b["text"] for b in buttons]
    assert "Sim" in titles
    assert "Não" in titles
    assert "Parar mensagens" in titles
```

- [ ] **Step 2: Rodar para confirmar que falha**

```bash
cd backend && python -m pytest tests/test_outbound_rehearsal_runner.py -v
```

Saída esperada: `ModuleNotFoundError` — runner não existe.

- [ ] **Step 3: Criar o runner com as funções auxiliares**

Criar `backend/scripts/outbound_rehearsal_runner.py`:

```python
"""Outbound Rehearsal Runner — valida a Valéria Outbound com 4 archetypes (O1-O4).

Uso:
    REHEARSAL_MODE=true uvicorn app.main:app --env-file .env.local --port 8001 &
    python -m scripts.outbound_rehearsal_runner          # roda O1-O4 em paralelo
    REHEARSAL_ONLY=O3 python -m scripts.outbound_rehearsal_runner  # roda só um

Envs necessárias (em .env.local):
    GEMINI_API_KEY, DEV_BACKEND_URL, SUPABASE_URL,
    SUPABASE_SERVICE_KEY, REDIS_URL
Opcionais:
    REHEARSAL_TURN_TIMEOUT (default 20), REHEARSAL_MAX_TURNS (default 20)
"""
import asyncio
import datetime as dt
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from app.config import settings  # noqa: E402
from scripts.rehearsal import supabase_io, logger as rlogger, gemini_actor, verifier  # noqa: E402
from scripts.rehearsal.outbound_archetypes import (  # noqa: E402
    ALL_OUTBOUND_ARCHETYPES,
    OutboundArchetype,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("outbound_rehearsal")

DEV_BACKEND_URL = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "rehearsal")
MAX_TURNS = int(os.environ.get("REHEARSAL_MAX_TURNS", "20"))
TURN_TIMEOUT = float(os.environ.get("REHEARSAL_TURN_TIMEOUT", "20"))
POLL_INTERVAL = 0.5
_MAX_CONNECT_RETRIES = 2
OUTPUT_ROOT = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "superpowers"
    / "plans"
    / "pilot"
    / "outbound-rehearsal-runs"
)


# ─── Payload builders ────────────────────────────────────────────────────────

def _build_button_reply_payload(phone: str, button_id: str, button_title: str) -> dict:
    """Monta payload webhook Meta para interactive/button_reply (quick reply)."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": META_PHONE_NUMBER_ID,
                        "display_phone_number": phone,
                    },
                    "contacts": [{"profile": {"name": "Rehearsal Lead"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.rehearsal.{uuid.uuid4().hex}",
                        "timestamp": str(int(time.time())),
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {
                                "id": button_id,
                                "title": button_title,
                            },
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _build_text_payload(phone: str, text: str) -> dict:
    """Monta payload webhook Meta para mensagem de texto simples."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": META_PHONE_NUMBER_ID,
                        "display_phone_number": phone,
                    },
                    "contacts": [{"profile": {"name": "Rehearsal Lead"}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": f"wamid.rehearsal.{uuid.uuid4().hex}",
                        "timestamp": str(int(time.time())),
                        "type": "text",
                        "text": {"body": text},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def _build_first_message_payload(phone: str, first_message) -> dict:
    """Dispatcher: retorna payload correto conforme tipo de first_message."""
    if isinstance(first_message, dict) and first_message.get("type") == "button_reply":
        return _build_button_reply_payload(
            phone,
            first_message["button_id"],
            first_message["button_title"],
        )
    return _build_text_payload(phone, str(first_message))


def build_outbound_template_payload(phone: str) -> dict:
    """Monta o payload do template de disparo inicial para envio via Meta Cloud API.

    NOTA: Este payload é para referência/documentação. O envio real via broadcast
    já é feito pela infra existente (broadcast/worker.py + MetaCloudClient.send_template).
    No contexto do Rehearsal, o lead já existe e a conversa começa com a resposta dele.
    """
    return {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "utilidade_22_04_2026_16_40",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "button",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": "Sim"},
                        {"type": "QUICK_REPLY", "text": "Não"},
                        {"type": "QUICK_REPLY", "text": "Parar mensagens"},
                    ],
                }
            ],
        },
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _utc_ts_path_component() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H-%M-%S")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _extract_stage_from_event(content: str) -> str | None:
    marker = "stage alterado para"
    low = content.lower()
    if marker in low:
        after = content[low.index(marker) + len(marker):].strip(": ,.")
        return after.split()[0].strip().lower() if after else None
    return None


def _terminated(archetype: OutboundArchetype, events: list[dict], turns: int) -> str | None:
    if turns >= MAX_TURNS:
        return "max_turns"
    for ev in events:
        content = ev.get("content", "").lower()
        if "encaminhado para" in content:
            return "encaminhar_humano"
    return None


def _render_inline(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        label = {"user": "Lead", "assistant": "Valeria", "system": "system"}.get(role, role)
        lines.append(f"[{label}] {m.get('content', '')}")
    return "\n".join(lines)


async def _health_check(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(f"{DEV_BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        log.info(f"Dev backend health OK ({DEV_BACKEND_URL})")
    except Exception as e:
        log.error(f"Dev backend health check failed: {e}")
        raise SystemExit(
            f"Dev backend em {DEV_BACKEND_URL} nao respondeu. "
            "Subir com REHEARSAL_MODE=true antes."
        )


async def _send_webhook(client: httpx.AsyncClient, payload: dict) -> None:
    for attempt in range(3):
        try:
            r = await client.post(
                f"{DEV_BACKEND_URL}/webhook/meta",
                json=payload,
                timeout=httpx.Timeout(connect=20.0, read=90.0, write=10.0, pool=15.0),
            )
            if r.status_code >= 400:
                log.warning(f"Webhook POST retornou {r.status_code}: {r.text[:200]}")
            return
        except (httpx.ReadError, httpx.ConnectError, httpx.PoolTimeout) as exc:
            wait = 2 ** attempt
            log.warning(
                f"Webhook POST falhou ({exc.__class__.__name__}) "
                f"tentativa {attempt + 1}/3 — aguardando {wait}s"
            )
            if attempt == 2:
                raise
            await asyncio.sleep(wait)


# ─── Archetype runner ────────────────────────────────────────────────────────

async def _run_outbound_archetype(
    archetype: OutboundArchetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
    phone: str,
) -> dict:
    log.info(f"[{archetype.id}] Iniciando ({archetype.slug}) phone={phone}")

    # Seed: limpa lead e buffer para começar do zero
    supabase_io.wipe_lead(phone)
    await supabase_io.wipe_redis_buffer(phone, redis)

    start_iso = _now_iso()

    # Dispara primeira mensagem (resposta ao template)
    first_payload = _build_first_message_payload(phone, archetype.first_message)
    for _attempt in range(_MAX_CONNECT_RETRIES + 1):
        try:
            await _send_webhook(client, first_payload)
            break
        except httpx.ConnectTimeout:
            if _attempt == _MAX_CONNECT_RETRIES:
                log.error(f"[{archetype.id}] ConnectTimeout apos {_MAX_CONNECT_RETRIES + 1} tentativas")
                return {
                    "archetype_id": archetype.id,
                    "archetype_slug": archetype.slug,
                    "status": "error",
                    "error": "ConnectTimeout",
                    "turns_count": 0,
                    "terminated_by": "crash",
                    "hard_checks": [],
                    "soft_check": {},
                    "stages_visited": [],
                }
            wait = 5.0 * (_attempt + 1)
            log.warning(f"[{archetype.id}] ConnectTimeout — tentativa {_attempt + 1}, aguardando {wait:.0f}s")
            await asyncio.sleep(wait)

    # Aguarda lead ser criado
    lead_id: str | None = None
    deadline = time.time() + TURN_TIMEOUT
    while time.time() < deadline and lead_id is None:
        await asyncio.sleep(POLL_INTERVAL)
        lead = supabase_io.get_lead_by_phone(phone)
        if lead:
            lead_id = lead["id"]

    if not lead_id:
        log.error(f"[{archetype.id}] Lead nao criado em {TURN_TIMEOUT}s — abortando")
        return {
            "archetype_id": archetype.id,
            "archetype_slug": archetype.slug,
            "status": "error",
            "error": "lead_not_created",
            "turns_count": 0,
            "terminated_by": "error",
            "soft_check": {},
            "hard_checks": [],
            "stages_visited": [],
        }

    # Loop de conversa
    turns = 1
    last_poll_iso = start_iso
    consecutive_timeouts = 0
    stages_visited: set[str] = set()
    terminated_by: str | None = None

    while True:
        valeria_msgs = []
        poll_deadline = time.time() + TURN_TIMEOUT
        while time.time() < poll_deadline:
            new_msgs = supabase_io.get_messages_since(lead_id, last_poll_iso)
            valeria_msgs = [m for m in new_msgs if m.get("role") == "assistant"]
            for m in new_msgs:
                if m.get("role") == "system":
                    stage = _extract_stage_from_event(m.get("content", ""))
                    if stage:
                        stages_visited.add(stage)
                        last_poll_iso = m["created_at"]
                if m.get("role") == "assistant":
                    last_poll_iso = m["created_at"]
            if valeria_msgs:
                break
            await asyncio.sleep(POLL_INTERVAL)

        if not valeria_msgs:
            consecutive_timeouts += 1
            log.warning(f"[{archetype.id}] Turno {turns} sem resposta (timeout #{consecutive_timeouts})")
            if consecutive_timeouts >= 2:
                terminated_by = "timeout"
                break
        else:
            consecutive_timeouts = 0

        events = supabase_io.get_system_events(lead_id)
        reason = _terminated(archetype, events, turns)
        if reason:
            terminated_by = reason
            break

        all_msgs = supabase_io.get_all_messages(lead_id)
        last_assistant = valeria_msgs[-1]["content"] if valeria_msgs else ""
        try:
            next_user_msg = gemini_actor.generate_next_lead_message(
                persona_prompt=archetype.persona_prompt,
                conversation_history=[{"role": m["role"], "content": m["content"]} for m in all_msgs],
                last_assistant_message=last_assistant,
            )
        except gemini_actor.GeminiFailure as e:
            log.error(f"[{archetype.id}] Gemini falhou — {e}")
            terminated_by = "gemini_error"
            break

        if not next_user_msg:
            log.warning(f"[{archetype.id}] Gemini retornou vazio — encerrando")
            terminated_by = "empty_gemini"
            break

        log.info(f"[{archetype.id}] Turno {turns + 1} — Lead: {next_user_msg[:80]}")
        await _send_webhook(client, _build_text_payload(phone, next_user_msg))
        turns += 1

        if turns >= MAX_TURNS:
            terminated_by = "max_turns"
            break

    all_messages = supabase_io.get_all_messages(lead_id)
    events = supabase_io.get_system_events(lead_id)
    run_data = {
        "events": events,
        "messages": all_messages,
        "turns_count": turns,
        "stages_visited": stages_visited,
        "terminated_by": terminated_by,
    }
    verification = verifier.verify(archetype, run_data, transcript=_render_inline(all_messages))

    rlogger.write_archetype_artifacts(
        run_dir=run_dir,
        archetype=archetype,
        messages=all_messages,
        events=events,
        verification=verification,
    )

    log.info(
        f"[{archetype.id}] Finalizado: status={verification['status']} "
        f"turns={turns} by={terminated_by}"
    )
    return verification


async def _run_with_jitter(
    idx: int,
    archetype: OutboundArchetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
    phone = f"5521{(90 + idx):08d}"  # Range diferente dos T1-T6 para evitar colisão
    log.info(f"[{archetype.id}] Agendado — phone={phone} jitter={idx * 2.0}s")
    await asyncio.sleep(idx * 2.0)
    return await _run_outbound_archetype(archetype, client, redis, run_dir, phone)


# ─── Main (NÃO chama gather — preparado mas não executado) ───────────────────

async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY nao definido em .env.local")

    if os.environ.get("REHEARSAL_MODE") != "true":
        raise SystemExit(
            "REHEARSAL_MODE nao esta setado como 'true'. "
            "Subir o backend com REHEARSAL_MODE=true antes de executar."
        )

    only = os.environ.get("REHEARSAL_ONLY")
    archetypes = [a for a in ALL_OUTBOUND_ARCHETYPES if (not only or a.id == only)]
    if not archetypes:
        raise SystemExit(f"Nenhum arquetipo encontrado com REHEARSAL_ONLY={only}")

    started_at = _now_iso()
    run_ts = _utc_ts_path_component()
    run_dir = OUTPUT_ROOT / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async with httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=30,
        ),
        timeout=httpx.Timeout(connect=20.0, read=90.0, write=10.0, pool=15.0),
    ) as client:
        await _health_check(client)

        # ── Execução paralela (prontos para rodar — aguardando autorização) ──
        # Para executar: remover o comentário abaixo e chamar asyncio.run(main())
        #
        # tasks = [
        #     _run_with_jitter(idx, archetype, client, redis, run_dir)
        #     for idx, archetype in enumerate(archetypes)
        # ]
        # raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        #
        # Por ora, sai após validar a infraestrutura:
        log.info(
            f"Infraestrutura pronta. {len(archetypes)} archetype(s) configurados: "
            + ", ".join(a.id for a in archetypes)
        )
        log.info("Para executar os testes, descomentar o bloco 'tasks' em main().")
        raw_results = []

    verifications: list[dict] = []
    for archetype, result in zip(archetypes, raw_results):
        if isinstance(result, BaseException):
            err_repr = f"{type(result).__name__}: {result}" if str(result) else type(result).__name__
            log.error(f"[{archetype.id}] Erro catastrofico: {err_repr}")
            verifications.append({
                "archetype_id": archetype.id,
                "archetype_slug": archetype.slug,
                "status": "error",
                "error": err_repr,
                "turns_count": 0,
                "terminated_by": "crash",
                "hard_checks": [],
                "soft_check": {},
                "stages_visited": [],
            })
        else:
            verifications.append(result)

    await redis.aclose()

    run_json = {
        "started_at": started_at,
        "finished_at": _now_iso(),
        "git_sha": _git_sha(),
        "archetypes": [a.id for a in archetypes],
        "dev_backend_url": DEV_BACKEND_URL,
        "phones": {a.id: f"5521{(90 + idx):08d}" for idx, a in enumerate(archetypes)},
        "gemini_model": gemini_actor.MODEL_NAME,
        "verifications": verifications,
        "mode": "infrastructure_ready_not_executed",
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_json, ensure_ascii=False, indent=2, default=str)
    )

    log.info(f"Run completo. Artefatos em: {run_dir}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

```bash
cd backend && python -m pytest tests/test_outbound_rehearsal_runner.py -v
```

Saída esperada: todos os 5 testes `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/outbound_rehearsal_runner.py backend/tests/test_outbound_rehearsal_runner.py
git commit -m "feat(rehearsal): outbound runner com payload builders e archetypes O1-O4"
```

---

## Task 4: Validação Final e Suite Completa

**Files:**
- Run: suite de testes dos 3 módulos novos

- [ ] **Step 1: Rodar toda a suite relacionada ao rehearsal**

```bash
cd backend && python -m pytest tests/test_outbound_archetypes.py tests/test_outbound_rehearsal_runner.py tests/test_handoff_rescue.py -v
```

Saída esperada: todos os testes `PASSED`, nenhum `ERROR`.

- [ ] **Step 2: Confirmar que a branch está limpa**

```bash
git status
git log --oneline -5
```

Saída esperada: `nothing to commit, working tree clean` e os 3 commits do plano visíveis.

- [ ] **Step 3: Avisar o usuário e aguardar autorização para push**

Conforme CLAUDE.md: **parar aqui e avisar o usuário**. O push para master aciona deploy de produção. Só executar `git push origin feature/outbound-rehearsal-setup:master` após autorização expressa.

---

## Resumo de Arquivos

| Arquivo | Status | O que faz |
|---------|--------|-----------|
| `backend/app/follow_up/service.py` | Modificado | Guard REHEARSAL_MODE em schedule_handoff_rescue |
| `backend/scripts/rehearsal/outbound_archetypes.py` | Criado | 4 archetypes O1–O4 |
| `backend/scripts/outbound_rehearsal_runner.py` | Criado | Runner completo com gather comentado |
| `backend/tests/test_outbound_archetypes.py` | Criado | Testes unitários dos archetypes |
| `backend/tests/test_outbound_rehearsal_runner.py` | Criado | Testes dos payload builders |
| `backend/tests/test_handoff_rescue.py` | Modificado | Caso de teste para REHEARSAL_MODE |

# Valéria Rehearsal Automático — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar um script Python que executa os 5 arquétipos A1-A5 do rehearsal de forma automática, com isolamento total entre leads, logs organizados, e verificação por arquétipo — tudo via Gemini 2.5 Pro atuando como lead e dev backend com `REHEARSAL_MODE=true` para evitar WhatsApp real.

**Architecture:** Script (`backend/scripts/rehearsal_runner.py`) que, para cada arquétipo, faz wipe no Supabase, abre um loop conversacional injetando mensagens via webhook Meta no dev backend, faz polling da tabela `messages` por respostas da Valéria, aplica hard checks + LLM-as-judge, persiste artefatos, e só então reseta e avança. Backend dev usa flag `REHEARSAL_MODE` que troca o provider real por um `MockProvider` (sem envio WhatsApp, apenas `save_message`).

**Tech Stack:** Python 3.12 + FastAPI (backend existente), Supabase (tabelas `leads`/`messages`/`conversations`/`deals`), Redis (buffer + dev_routes), OpenAI GPT-4.1-mini (Valéria, inalterado), Google Gemini 2.5 Pro (ator dos arquétipos via `google-generativeai`), httpx (POST webhook).

**Spec de referência:** `docs/superpowers/specs/2026-04-20-valeria-rehearsal-automatico-design.md`

---

## Arquivos a criar/modificar

**Novos:**
- `backend/app/whatsapp/mock_provider.py`
- `backend/tests/test_mock_provider.py`
- `backend/scripts/__init__.py` (se não existir)
- `backend/scripts/rehearsal/__init__.py`
- `backend/scripts/rehearsal/archetypes.py`
- `backend/scripts/rehearsal/supabase_io.py`
- `backend/scripts/rehearsal/gemini_actor.py`
- `backend/scripts/rehearsal/verifier.py`
- `backend/scripts/rehearsal/logger.py`
- `backend/scripts/rehearsal_runner.py`
- `backend/tests/test_rehearsal_supabase_io.py`
- `backend/tests/test_rehearsal_verifier.py`
- `backend/tests/test_rehearsal_logger.py`
- `backend/tests/test_rehearsal_gemini_actor.py`

**Modificar:**
- `backend/app/whatsapp/registry.py` — conditional mock
- `backend/requirements.txt` — `google-generativeai`
- `backend/.env.example` — novas variáveis (nunca tocar `.env.local` do usuário via script)
- `.vscode/tasks.json` — adicionar task `Run Rehearsal (all archetypes)` (se o arquivo existir — checar primeiro)

---

## Task 0.1: Preparar worktree

**Files:** nenhum (operação git)

- [ ] **Step 1: Verificar que `.worktrees` está no `.gitignore`**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
git check-ignore -q .worktrees && echo "ok" || echo "FALTA ADICIONAR"
```

Expected: `ok`.

- [ ] **Step 2: Criar worktree com nova branch**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra"
git worktree add .worktrees/valeria-rehearsal -b feature/valeria-rehearsal
cd .worktrees/valeria-rehearsal
```

Expected: `Preparing worktree (new branch 'feature/valeria-rehearsal')`.

- [ ] **Step 3: Rodar testes baseline**

```bash
cd backend && python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: todos passando. Se falhar, PARAR e avisar o usuário antes de seguir.

**Nenhum commit nesta task.**

---

## Task 1.1: MockProvider

**Files:**
- Create: `backend/app/whatsapp/mock_provider.py`
- Create: `backend/tests/test_mock_provider.py`

- [ ] **Step 1: Escrever testes falhando**

Em `backend/tests/test_mock_provider.py`:

```python
import asyncio
import json
import os
from pathlib import Path

import pytest

from app.whatsapp.mock_provider import MockProvider


@pytest.mark.asyncio
async def test_send_text_logs_and_returns_ok(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({"name": "test"})

    result = await provider.send_text("+5500000000", "ola")

    assert result["status"] == "mock_ok"
    lines = log_file.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["method"] == "send_text"
    assert entry["to"] == "+5500000000"
    assert entry["body"] == "ola"


@pytest.mark.asyncio
async def test_send_image_base64_logs_summary(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({})

    await provider.send_image_base64("+5500000000", "A" * 10000, caption="foto")

    entry = json.loads(log_file.read_text().splitlines()[0])
    assert entry["method"] == "send_image_base64"
    assert entry["caption"] == "foto"
    assert "base64_size_bytes" in entry
    assert entry["base64_size_bytes"] == 10000


@pytest.mark.asyncio
async def test_send_template_logs(tmp_path, monkeypatch):
    log_file = tmp_path / "rehearsal.jsonl"
    monkeypatch.setenv("REHEARSAL_LOG_PATH", str(log_file))
    provider = MockProvider({})

    await provider.send_template("+5500000000", "tpl_outbound", {"body": ["Joao"]})

    entry = json.loads(log_file.read_text().splitlines()[0])
    assert entry["method"] == "send_template"
    assert entry["template_name"] == "tpl_outbound"


@pytest.mark.asyncio
async def test_no_log_file_if_env_unset(monkeypatch):
    monkeypatch.delenv("REHEARSAL_LOG_PATH", raising=False)
    provider = MockProvider({})
    result = await provider.send_text("+5500000000", "ola")
    assert result["status"] == "mock_ok"
```

- [ ] **Step 2: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_mock_provider.py -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.whatsapp.mock_provider'`.

- [ ] **Step 3: Implementar MockProvider**

Em `backend/app/whatsapp/mock_provider.py`:

```python
import json
import logging
import os
import time
from pathlib import Path

from app.whatsapp.base import WhatsAppProvider

logger = logging.getLogger(__name__)


def _log_entry(entry: dict) -> None:
    """Append an entry to the rehearsal log file if REHEARSAL_LOG_PATH is set."""
    path = os.environ.get("REHEARSAL_LOG_PATH")
    if not path:
        return
    entry["timestamp"] = time.time()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MockProvider(WhatsAppProvider):
    """WhatsApp provider stub used during REHEARSAL_MODE. Never sends real messages."""

    def __init__(self, config: dict):
        self.config = config or {}

    async def send_text(self, to: str, body: str) -> dict:
        logger.warning(f"[MOCK] send_text to={to} body={body[:60]!r}")
        _log_entry({"method": "send_text", "to": to, "body": body})
        return {"status": "mock_ok", "method": "send_text"}

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        logger.warning(f"[MOCK] send_image to={to} url={image_url}")
        _log_entry({"method": "send_image", "to": to, "image_url": image_url, "caption": caption})
        return {"status": "mock_ok", "method": "send_image"}

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        logger.warning(f"[MOCK] send_image_base64 to={to} size={len(base64_data)}")
        _log_entry({
            "method": "send_image_base64",
            "to": to,
            "mimetype": mimetype,
            "caption": caption,
            "base64_size_bytes": len(base64_data),
        })
        return {"status": "mock_ok", "method": "send_image_base64"}

    async def send_audio(self, to: str, audio_url: str) -> dict:
        logger.warning(f"[MOCK] send_audio to={to} url={audio_url}")
        _log_entry({"method": "send_audio", "to": to, "audio_url": audio_url})
        return {"status": "mock_ok", "method": "send_audio"}

    async def send_template(self, to: str, template_name: str, components: dict | None = None, language_code: str = "pt_BR") -> dict:
        logger.warning(f"[MOCK] send_template to={to} template={template_name}")
        _log_entry({
            "method": "send_template",
            "to": to,
            "template_name": template_name,
            "components": components,
            "language_code": language_code,
        })
        return {"status": "mock_ok", "method": "send_template"}

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        _log_entry({"method": "mark_read", "message_id": message_id})
        return {"status": "mock_ok", "method": "mark_read"}
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_mock_provider.py -v 2>&1 | tail -10
```

Expected: 4 testes PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal"
git add backend/app/whatsapp/mock_provider.py backend/tests/test_mock_provider.py
git commit -m "feat(whatsapp): adicionar MockProvider para REHEARSAL_MODE"
```

---

## Task 1.2: Registry conditional em REHEARSAL_MODE

**Files:**
- Modify: `backend/app/whatsapp/registry.py`
- Create: `backend/tests/test_registry_rehearsal.py`

- [ ] **Step 1: Escrever testes falhando**

Em `backend/tests/test_registry_rehearsal.py`:

```python
import pytest

from app.whatsapp.registry import get_provider
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.meta import MetaCloudClient


def test_returns_mock_when_rehearsal_mode(monkeypatch):
    monkeypatch.setenv("REHEARSAL_MODE", "true")
    channel = {"provider": "meta_cloud", "provider_config": {}}
    provider = get_provider(channel)
    assert isinstance(provider, MockProvider)


def test_returns_real_when_rehearsal_mode_unset(monkeypatch):
    monkeypatch.delenv("REHEARSAL_MODE", raising=False)
    channel = {"provider": "meta_cloud", "provider_config": {}}
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)


def test_rehearsal_mode_false_also_returns_real(monkeypatch):
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"provider": "meta_cloud", "provider_config": {}}
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)
```

- [ ] **Step 2: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_registry_rehearsal.py -v 2>&1 | tail -10
```

Expected: FAIL em `test_returns_mock_when_rehearsal_mode` (volta o real).

- [ ] **Step 3: Modificar `registry.py`**

Substituir o conteúdo de `backend/app/whatsapp/registry.py`:

```python
import os

from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient
from app.whatsapp.mock_provider import MockProvider

_PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    "evolution": EvolutionClient,
    "meta_cloud": MetaCloudClient,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve the correct WhatsAppProvider instance from a channel record.

    When REHEARSAL_MODE=true, returns a MockProvider instead — used during
    automated rehearsal so Valéria's outbound messages are not sent via real
    WhatsApp. The mock still logs and triggers save_message paths elsewhere,
    preserving the orchestrator flow.
    """
    if os.environ.get("REHEARSAL_MODE", "").lower() == "true":
        return MockProvider(channel.get("provider_config", {}))

    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type!r}. Expected one of: {list(_PROVIDERS)}")
    return provider_class(channel.get("provider_config", {}))
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_registry_rehearsal.py tests/test_mock_provider.py -v 2>&1 | tail -10
```

Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whatsapp/registry.py backend/tests/test_registry_rehearsal.py
git commit -m "feat(whatsapp): registry retorna MockProvider quando REHEARSAL_MODE=true"
```

---

## Task 2.1: Supabase IO helpers

**Files:**
- Create: `backend/scripts/__init__.py` (vazio, se não existir)
- Create: `backend/scripts/rehearsal/__init__.py` (vazio)
- Create: `backend/scripts/rehearsal/supabase_io.py`
- Create: `backend/tests/test_rehearsal_supabase_io.py`

- [ ] **Step 1: Criar `__init__.py` vazios**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/backend"
mkdir -p scripts/rehearsal
touch scripts/__init__.py scripts/rehearsal/__init__.py
```

- [ ] **Step 2: Escrever testes falhando**

Em `backend/tests/test_rehearsal_supabase_io.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from scripts.rehearsal import supabase_io


def _make_sb_chain(return_data=None):
    """Build a mock Supabase client that returns chained .table().select().eq()... calls."""
    sb = MagicMock()
    table = MagicMock()
    sb.table.return_value = table
    table.select.return_value = table
    table.delete.return_value = table
    table.eq.return_value = table
    table.gt.return_value = table
    table.order.return_value = table
    result = MagicMock()
    result.data = return_data or []
    table.execute.return_value = result
    return sb, table


def test_wipe_lead_deletes_in_right_order(monkeypatch):
    sb, table = _make_sb_chain(return_data=[{"id": "lead-1"}])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    supabase_io.wipe_lead("5500000000")

    # sb.table() called in order: leads (to find id), then messages, conversations, deals, leads (delete)
    table_calls = [call.args[0] for call in sb.table.call_args_list]
    # first call to find lead id
    assert table_calls[0] == "leads"
    # subsequent calls: messages, conversations, deals, leads (delete)
    assert "messages" in table_calls
    assert "conversations" in table_calls
    assert "deals" in table_calls


def test_wipe_lead_no_lead_is_noop(monkeypatch):
    sb, table = _make_sb_chain(return_data=[])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    # Should not raise
    supabase_io.wipe_lead("5500000000")


def test_get_messages_since_filters_by_timestamp(monkeypatch):
    sb, table = _make_sb_chain(return_data=[{"role": "assistant", "content": "oi"}])
    monkeypatch.setattr(supabase_io, "get_supabase", lambda: sb)

    result = supabase_io.get_messages_since("lead-id", "2026-04-20T10:00:00Z")

    assert len(result) == 1
    assert result[0]["role"] == "assistant"
    # Confirm .gt("created_at", ...) was called
    table.gt.assert_called_with("created_at", "2026-04-20T10:00:00Z")


def test_wipe_redis_buffer_deletes_all_keys():
    from unittest.mock import AsyncMock
    redis = AsyncMock()
    # sync wrapper
    import asyncio

    asyncio.run(supabase_io.wipe_redis_buffer("5500000000", redis))

    # Must delete: buffer:<phone>, buffer:<phone>:lock, buffer:<phone>:deadline,
    # pushname:<phone>, channel:<phone>
    deleted_keys = [call.args[0] for call in redis.delete.call_args_list]
    assert "buffer:5500000000" in deleted_keys
    assert "buffer:5500000000:lock" in deleted_keys
    assert "buffer:5500000000:deadline" in deleted_keys
    assert "pushname:5500000000" in deleted_keys
    assert "channel:5500000000" in deleted_keys
```

- [ ] **Step 3: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_rehearsal_supabase_io.py -v 2>&1 | tail -10
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implementar `supabase_io.py`**

Em `backend/scripts/rehearsal/supabase_io.py`:

```python
"""Supabase helpers for the rehearsal runner.

Reuses the backend's Supabase client (service-role credentials already configured).
"""
import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def get_lead_by_phone(phone: str) -> dict | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


def wipe_lead(phone: str) -> None:
    """Delete lead and all related rows. Safe to call when no lead exists."""
    sb = get_supabase()
    lead = get_lead_by_phone(phone)
    if not lead:
        logger.info(f"wipe_lead: no lead for {phone}, nothing to delete")
        return
    lead_id = lead["id"]
    # Order matters due to foreign keys: children first
    for table in ("messages", "conversations", "deals"):
        sb.table(table).delete().eq("lead_id", lead_id).execute()
    sb.table("leads").delete().eq("id", lead_id).execute()
    logger.info(f"wipe_lead: deleted lead {lead_id} (phone={phone})")


def get_messages_since(lead_id: str, since_iso: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .gt("created_at", since_iso)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_all_messages(lead_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_system_events(lead_id: str) -> list[dict[str, Any]]:
    """Return messages with role=system. The orchestrator saves tool effects
    (stage changes, forwarding, pedido registered, photos sent) with role=system,
    so this list is the canonical event log for verification."""
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id, content, stage, created_at")
        .eq("lead_id", lead_id)
        .eq("role", "system")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


async def wipe_redis_buffer(phone: str, redis) -> None:
    """Delete all buffer/state Redis keys scoped to this phone number.

    Matches the key patterns from backend/app/buffer/manager.py and
    backend/app/buffer/flusher.py.
    """
    keys = [
        f"buffer:{phone}",
        f"buffer:{phone}:lock",
        f"buffer:{phone}:deadline",
        f"pushname:{phone}",
        f"channel:{phone}",
    ]
    for key in keys:
        await redis.delete(key)
```

- [ ] **Step 5: Rodar testes**

```bash
cd backend && python -m pytest tests/test_rehearsal_supabase_io.py -v 2>&1 | tail -15
```

Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/ backend/tests/test_rehearsal_supabase_io.py
git commit -m "feat(rehearsal): adicionar helpers de Supabase IO (wipe_lead, get_messages_since, wipe_redis_buffer)"
```

---

## Task 2.2: Arquétipos

**Files:**
- Create: `backend/scripts/rehearsal/archetypes.py`

- [ ] **Step 1: Implementar arquétipos**

Em `backend/scripts/rehearsal/archetypes.py`:

```python
"""The 5 archetypes used for rehearsal. Data-only — no I/O."""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Archetype:
    id: str
    slug: str
    persona_prompt: str
    first_message: str
    # Hard checks are callables that receive run_data dict and return (passed, reason).
    # run_data shape: {"events": [...], "messages": [...], "turns_count": int, "stages_visited": set[str]}
    hard_checks: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)


# Helpers to build common checks reusable across archetypes
def has_tool_call(name: str):
    def check(run_data: dict) -> tuple[bool, str]:
        events = run_data.get("events", [])
        for ev in events:
            content = ev.get("content", "")
            if name in content.lower():
                return True, f"{name} presente nos eventos"
        return False, f"{name} nao foi chamada"
    check.__name__ = f"has_{name}"
    return check


def reached_stage(stage: str):
    def check(run_data: dict) -> tuple[bool, str]:
        if stage in run_data.get("stages_visited", set()):
            return True, f"stage {stage} alcancado"
        return False, f"stage {stage} NAO alcancado"
    check.__name__ = f"reached_{stage}"
    return check


def visited_multiple_stages(min_count: int = 2):
    def check(run_data: dict) -> tuple[bool, str]:
        count = len(run_data.get("stages_visited", set()))
        if count >= min_count:
            return True, f"{count} stages visitados"
        return False, f"apenas {count} stage(s) visitado(s)"
    check.__name__ = f"visited_gte_{min_count}_stages"
    return check


def min_turns(n: int):
    def check(run_data: dict) -> tuple[bool, str]:
        turns = run_data.get("turns_count", 0)
        if turns >= n:
            return True, f"{turns} turnos (>= {n})"
        return False, f"apenas {turns} turno(s)"
    check.__name__ = f"min_{n}_turns"
    return check


def transcript_matches(pattern: str, description: str):
    import re
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        text = "\n".join(m.get("content", "") for m in messages)
        if compiled.search(text):
            return True, f"{description} (match)"
        return False, f"{description} (sem match)"
    check.__name__ = f"regex_{description}"
    return check


# --- Archetype definitions ---

_A1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: dono de uma cafeteria pequena em Belo Horizonte. Tem 1 loja, compra cerca de 10kg/mes de um torrefador local, esta cogitando trocar de fornecedor.
Tom: direto, ocupado, portugues informal brasileiro. Erra acentos de vez em quando, frases curtas.
Comportamento:
- Pergunta preco logo no inicio
- Pede amostra
- Pergunta MOQ (pedido minimo) e entrega pra BH
- Se for convencido, confirma intencao de comprar ~10kg e pede pra fechar
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

A1 = Archetype(
    id="A1",
    slug="cafeteria-atacado",
    persona_prompt=_A1_PERSONA,
    first_message="oi, vi a mensagem. o que voces tem de cafe?",
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("enviar_foto"),  # matches both enviar_fotos and enviar_foto_produto
        transcript_matches(r"\d+\s*(kg|quilos?)", "mencao de volume em kg"),
    ],
)


_A2_PERSONA = """Voce esta interpretando um LEAD.

Papel: influenciador de cafe (15k seguidores) querendo lancar a propria marca de cafe em 2026.
Tom: entusiasmado, perguntas sobre branding, fala informal mas articulado.
Comportamento:
- Pergunta se a empresa faz marca propria (private label)
- Pergunta quantidade minima, prazo, custo de embalagem personalizada, uso do proprio design
- Quer detalhes do processo e contato com humano pra avancar

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A2 = Archetype(
    id="A2",
    slug="private-label",
    persona_prompt=_A2_PERSONA,
    first_message="voces fazem marca propria?",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
    ],
)


_A3_PERSONA = """Voce esta interpretando um LEAD com duplo interesse.

Papel: tem uma cafeteria ATIVA em operacao hoje (compra atacado) E quer lancar uma MARCA PROPRIA de cafe em 2027.
Tom: direto, profissional, quer explorar os dois lados numa conversa so.
Comportamento:
- Deixa claro que tem interesse nas DUAS coisas
- Insiste se a Valeria tentar focar so num
- Espera respostas que cubram ambos os modelos de negocio

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A3 = Archetype(
    id="A3",
    slug="multi-intent",
    persona_prompt=_A3_PERSONA,
    first_message="tenho uma cafeteria mas tambem penso em criar minha marca de cafe. da pra falar dos dois?",
    hard_checks=[
        visited_multiple_stages(2),
    ],
)


_A4_PERSONA = """Voce esta interpretando um LEAD cetico/objetor.

Papel: ja tem um fornecedor de cafe, esta curioso mas resistente.
Tom: seco, confronta, pede justificativas. Nao e grosseiro mas nao compra papinho.
Comportamento:
- Abre dizendo que ja tem fornecedor
- Menciona preco do fornecedor atual (inventa algo plausivel, R$ 35/kg)
- Pergunta diferencial, prazo, qualidade
- NAO fecha facil — tem que ser convencido com argumentos concretos

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A4 = Archetype(
    id="A4",
    slug="objetor-preco",
    persona_prompt=_A4_PERSONA,
    first_message="ja tenho fornecedor, mas me conta o que voces tem de diferente",
    hard_checks=[
        reached_stage("atacado"),
        min_turns(5),
    ],
)


_A5_PERSONA = """Voce esta interpretando um LEAD internacional.

Papel: brasileiro morando em Portugal, vai abrir uma cafeteria em Lisboa no segundo semestre de 2026. Quer importar cafe brasileiro.
Tom: cordial, perguntas sobre logistica internacional, portugues brasileiro.
Comportamento:
- Primeira mensagem deixa claro que e para CAFETERIA EM LISBOA (nao consumo pessoal)
- Pergunta sobre exportacao, prazos, documentacao
- Quer ser encaminhado pra alguem que entenda de exportacao

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A5 = Archetype(
    id="A5",
    slug="exportacao",
    persona_prompt=_A5_PERSONA,
    first_message="vou abrir um cafe em Lisboa no segundo semestre. voces exportam?",
    hard_checks=[
        reached_stage("exportacao"),
        has_tool_call("encaminhar_humano"),
    ],
)


ALL_ARCHETYPES = [A1, A2, A3, A4, A5]
```

- [ ] **Step 2: Smoke test (import + estrutura)**

Criar temporariamente um teste rápido:

```bash
cd backend && python -c "from scripts.rehearsal.archetypes import ALL_ARCHETYPES; print([a.id for a in ALL_ARCHETYPES])"
```

Expected: `['A1', 'A2', 'A3', 'A4', 'A5']`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/rehearsal/archetypes.py
git commit -m "feat(rehearsal): definir 5 arquetipos A1-A5 com persona prompt e hard checks"
```

---

## Task 2.3: Gemini Actor

**Files:**
- Create: `backend/scripts/rehearsal/gemini_actor.py`
- Create: `backend/tests/test_rehearsal_gemini_actor.py`

- [ ] **Step 1: Adicionar dependência (ainda não instalar — o plano instala na Task 3.1)**

Registrar o que precisa ser adicionado: `google-generativeai>=0.8.0` em `backend/requirements.txt`. Não commitar agora.

- [ ] **Step 2: Escrever testes falhando**

Em `backend/tests/test_rehearsal_gemini_actor.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from scripts.rehearsal import gemini_actor


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_next_lead_message_returns_stripped_text(mock_get_model):
    model = MagicMock()
    response = MagicMock()
    response.text = "  qual o preco?  \n"
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.generate_next_lead_message(
        persona_prompt="voce e um lead",
        conversation_history=[
            {"role": "assistant", "content": "oi, em que posso ajudar?"},
        ],
        last_assistant_message="oi, em que posso ajudar?",
    )

    assert result == "qual o preco?"
    model.generate_content.assert_called_once()


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_retries_on_exception(mock_get_model):
    model = MagicMock()
    # Fail twice, succeed on third
    response_ok = MagicMock(text="ok")
    model.generate_content.side_effect = [Exception("rate limit"), Exception("500"), response_ok]
    mock_get_model.return_value = model

    result = gemini_actor.generate_next_lead_message("persona", [], "")

    assert result == "ok"
    assert model.generate_content.call_count == 3


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_generate_gives_up_after_max_retries(mock_get_model):
    model = MagicMock()
    model.generate_content.side_effect = Exception("persistent error")
    mock_get_model.return_value = model

    with pytest.raises(gemini_actor.GeminiFailure):
        gemini_actor.generate_next_lead_message("persona", [], "")


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_judge_conversation_parses_json(mock_get_model):
    model = MagicMock()
    response = MagicMock()
    response.text = '''```json
{
  "bot_score_1_10": 8,
  "linhas_robotizadas": ["soou strange"],
  "resposta_incorreta_ou_inventada": null,
  "veredito_curto": "chegou ao objetivo"
}
```'''
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.judge_conversation(
        transcript="conversa completa aqui",
        archetype_id="A1",
        criteria_description="critérios do A1",
    )

    assert result["bot_score_1_10"] == 8
    assert result["veredito_curto"] == "chegou ao objetivo"


@patch("scripts.rehearsal.gemini_actor._get_model")
def test_judge_falls_back_on_invalid_json(mock_get_model):
    model = MagicMock()
    response = MagicMock(text="isto nao eh json")
    model.generate_content.return_value = response
    mock_get_model.return_value = model

    result = gemini_actor.judge_conversation("x", "A1", "y")

    assert "error" in result
    assert result.get("bot_score_1_10") is None
```

- [ ] **Step 3: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_rehearsal_gemini_actor.py -v 2>&1 | tail -10
```

Expected: FAIL — módulo não existe.

- [ ] **Step 4: Implementar `gemini_actor.py`**

Em `backend/scripts/rehearsal/gemini_actor.py`:

```python
"""Gemini 2.5 Pro wrapper — plays lead archetypes and judges conversations.

Lazy imports of google.generativeai so tests don't require the package to be
installed to run (they monkeypatch _get_model).
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-pro"
MAX_RETRIES = 3


class GeminiFailure(Exception):
    """Raised when Gemini calls fail after max retries."""


def _get_model():
    """Lazy-build the Gemini model. Overridable in tests via monkeypatch."""
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiFailure("GEMINI_API_KEY not set in environment")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(MODEL_NAME)


def _with_retry(call, *args, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return call(*args, **kwargs)
        except Exception as e:
            last_err = e
            backoff = 2 ** attempt
            logger.warning(f"Gemini call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. Retrying in {backoff}s")
            time.sleep(backoff)
    raise GeminiFailure(f"Gemini call failed after {MAX_RETRIES} retries: {last_err}")


def _format_history(conversation_history: list[dict]) -> str:
    lines = []
    for msg in conversation_history:
        role = msg.get("role", "?")
        content = msg.get("content", "").strip()
        label = {"assistant": "Atendente", "user": "Lead", "system": "[sistema]"}.get(role, role)
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def generate_next_lead_message(
    persona_prompt: str,
    conversation_history: list[dict],
    last_assistant_message: str,
) -> str:
    """Ask Gemini to produce the lead's next message in character."""
    history_text = _format_history(conversation_history) or "(conversa ainda nao comecou)"
    prompt = f"""{persona_prompt}

=== Historico da conversa ate agora ===
{history_text}

=== Ultima mensagem da Atendente ===
{last_assistant_message.strip() or "(nao enviou nada ainda)"}

=== Sua proxima mensagem como Lead ==="""

    def _call():
        model = _get_model()
        response = model.generate_content(prompt)
        return response.text.strip() if response.text else ""

    text = _with_retry(_call)
    return text.strip()


def judge_conversation(transcript: str, archetype_id: str, criteria_description: str) -> dict:
    """Ask Gemini to judge a completed rehearsal conversation."""
    prompt = f"""Voce eh um avaliador de qualidade de um agente de vendas por WhatsApp chamado Valeria.

Arquetipo de lead testado: {archetype_id}
Criterios esperados: {criteria_description}

=== Transcricao da conversa ===
{transcript}

=== Avalie em JSON puro ===
Responda APENAS com um JSON valido (sem explicacao adicional) neste formato:
{{
  "bot_score_1_10": <inteiro 1-10, 10=soa totalmente humano>,
  "linhas_robotizadas": [<strings literais das frases da Valeria que pareceram roboticas>],
  "resposta_incorreta_ou_inventada": <string descrevendo ou null>,
  "veredito_curto": <string em 1 frase: resumo do desempenho>
}}"""

    def _call():
        model = _get_model()
        response = model.generate_content(prompt)
        return response.text or ""

    try:
        raw = _with_retry(_call)
    except GeminiFailure as e:
        return {"error": str(e), "bot_score_1_10": None}

    # Extract JSON from possibly fenced response
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"error": "no_json_found", "raw": raw[:500], "bot_score_1_10": None}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"invalid_json: {e}", "raw": raw[:500], "bot_score_1_10": None}
```

- [ ] **Step 5: Rodar testes**

```bash
cd backend && python -m pytest tests/test_rehearsal_gemini_actor.py -v 2>&1 | tail -15
```

Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/rehearsal/gemini_actor.py backend/tests/test_rehearsal_gemini_actor.py
git commit -m "feat(rehearsal): Gemini 2.5 Pro actor para leads simulados + LLM-as-judge"
```

---

## Task 2.4: Verifier

**Files:**
- Create: `backend/scripts/rehearsal/verifier.py`
- Create: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Escrever testes falhando**

Em `backend/tests/test_rehearsal_verifier.py`:

```python
from unittest.mock import patch

from scripts.rehearsal import verifier
from scripts.rehearsal.archetypes import A1


def test_hard_checks_all_pass_returns_passed():
    run_data = {
        "events": [{"content": "stage alterado para atacado"}, {"content": "2 fotos de atacado enviadas"}],
        "messages": [{"content": "quero 10kg"}],
        "turns_count": 12,
        "stages_visited": {"atacado"},
    }

    result = verifier.run_hard_checks(A1, run_data)

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["checks"])


def test_hard_checks_fail_if_any_missing():
    run_data = {
        "events": [],
        "messages": [],
        "turns_count": 1,
        "stages_visited": set(),
    }

    result = verifier.run_hard_checks(A1, run_data)

    assert result["status"] == "failed"
    assert any(not c["passed"] for c in result["checks"])


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_combines_hard_and_soft(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 7, "veredito_curto": "bom"}
    run_data = {
        "events": [{"content": "stage alterado para atacado"}, {"content": "foto_produto classico enviada"}],
        "messages": [{"content": "quero 10kg por favor"}],
        "turns_count": 10,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(A1, run_data, transcript="conversa aqui")

    assert result["status"] == "passed"
    assert result["soft_check"]["bot_score_1_10"] == 7
    assert result["archetype_id"] == "A1"
    assert result["turns_count"] == 10
```

- [ ] **Step 2: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_rehearsal_verifier.py -v 2>&1 | tail -10
```

Expected: FAIL.

- [ ] **Step 3: Implementar `verifier.py`**

Em `backend/scripts/rehearsal/verifier.py`:

```python
"""Verification for a single archetype run. Hard checks (deterministic) +
soft check (LLM-as-judge)."""
from scripts.rehearsal.archetypes import Archetype
from scripts.rehearsal.gemini_actor import judge_conversation


def run_hard_checks(archetype: Archetype, run_data: dict) -> dict:
    results = []
    for check in archetype.hard_checks:
        passed, reason = check(run_data)
        results.append({"name": check.__name__, "passed": passed, "reason": reason})
    status = "passed" if all(r["passed"] for r in results) else "failed"
    return {"status": status, "checks": results}


def _criteria_summary(archetype: Archetype) -> str:
    names = [c.__name__ for c in archetype.hard_checks]
    return f"Checks: {', '.join(names)}"


def verify(archetype: Archetype, run_data: dict, transcript: str) -> dict:
    hard = run_hard_checks(archetype, run_data)
    soft = judge_conversation(
        transcript=transcript,
        archetype_id=archetype.id,
        criteria_description=_criteria_summary(archetype),
    )
    return {
        "archetype_id": archetype.id,
        "archetype_slug": archetype.slug,
        "status": hard["status"],
        "hard_checks": hard["checks"],
        "soft_check": soft,
        "turns_count": run_data.get("turns_count", 0),
        "terminated_by": run_data.get("terminated_by", "unknown"),
        "stages_visited": sorted(run_data.get("stages_visited", set())),
    }
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_rehearsal_verifier.py -v 2>&1 | tail -10
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rehearsal/verifier.py backend/tests/test_rehearsal_verifier.py
git commit -m "feat(rehearsal): verifier com hard checks + soft check LLM-as-judge"
```

---

## Task 2.5: Logger de artefatos

**Files:**
- Create: `backend/scripts/rehearsal/logger.py`
- Create: `backend/tests/test_rehearsal_logger.py`

- [ ] **Step 1: Escrever testes falhando**

Em `backend/tests/test_rehearsal_logger.py`:

```python
import json

from scripts.rehearsal import logger as rehearsal_logger
from scripts.rehearsal.archetypes import A1


def test_write_artifacts_creates_expected_files(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()

    messages = [
        {"role": "user", "content": "oi", "created_at": "2026-04-20T10:00:00Z"},
        {"role": "assistant", "content": "oi, em que posso ajudar?", "created_at": "2026-04-20T10:00:02Z"},
    ]
    events = [
        {"content": "stage alterado para atacado", "created_at": "2026-04-20T10:00:03Z"},
    ]
    verification = {"status": "passed", "archetype_id": "A1"}

    archetype_dir = rehearsal_logger.write_archetype_artifacts(
        run_dir=run_dir,
        archetype=A1,
        messages=messages,
        events=events,
        verification=verification,
    )

    assert archetype_dir.name == "A1-cafeteria-atacado"
    assert (archetype_dir / "transcript.md").exists()
    assert (archetype_dir / "events.jsonl").exists()
    assert (archetype_dir / "messages.json").exists()
    assert (archetype_dir / "verification.json").exists()
    assert (archetype_dir / "archetype-prompt.md").exists()

    transcript = (archetype_dir / "transcript.md").read_text()
    assert "oi" in transcript
    assert "em que posso ajudar" in transcript

    events_content = (archetype_dir / "events.jsonl").read_text().splitlines()
    assert len(events_content) == 1
    assert json.loads(events_content[0])["content"] == "stage alterado para atacado"

    v = json.loads((archetype_dir / "verification.json").read_text())
    assert v["status"] == "passed"


def test_write_run_summary(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()

    verifications = [
        {"archetype_id": "A1", "archetype_slug": "cafeteria-atacado", "status": "passed",
         "turns_count": 10, "terminated_by": "encaminhar_humano",
         "soft_check": {"bot_score_1_10": 7, "veredito_curto": "bom"}},
        {"archetype_id": "A2", "archetype_slug": "private-label", "status": "failed",
         "turns_count": 5, "terminated_by": "max_turns",
         "soft_check": {"bot_score_1_10": 4, "veredito_curto": "travou"}},
    ]

    rehearsal_logger.write_run_summary(run_dir, verifications, run_meta={"started_at": "2026-04-20T10:00:00Z"})

    summary = (run_dir / "summary.md").read_text()
    assert "A1" in summary
    assert "A2" in summary
    assert "passed" in summary
    assert "failed" in summary

    run_json = json.loads((run_dir / "run.json").read_text())
    assert run_json["started_at"] == "2026-04-20T10:00:00Z"
    assert len(run_json["verifications"]) == 2
```

- [ ] **Step 2: Confirmar falha**

```bash
cd backend && python -m pytest tests/test_rehearsal_logger.py -v 2>&1 | tail -10
```

Expected: FAIL.

- [ ] **Step 3: Implementar `logger.py`**

Em `backend/scripts/rehearsal/logger.py`:

```python
"""Persists artifacts from a rehearsal run to disk."""
import json
from pathlib import Path

from scripts.rehearsal.archetypes import Archetype


def _render_transcript(messages: list[dict], archetype: Archetype) -> str:
    lines = [f"# Transcript — {archetype.id} ({archetype.slug})", ""]
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "?")
        content = msg.get("content", "").strip()
        ts = msg.get("created_at", "")
        if role == "user":
            lines.append(f"### Turno {i} — Lead ({ts})")
        elif role == "assistant":
            lines.append(f"### Turno {i} — Valeria ({ts})")
        elif role == "system":
            lines.append(f"### [system] ({ts})")
        else:
            lines.append(f"### {role} ({ts})")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def write_archetype_artifacts(
    run_dir: Path,
    archetype: Archetype,
    messages: list[dict],
    events: list[dict],
    verification: dict,
) -> Path:
    archetype_dir = run_dir / f"{archetype.id}-{archetype.slug}"
    archetype_dir.mkdir(parents=True, exist_ok=True)

    (archetype_dir / "transcript.md").write_text(_render_transcript(messages, archetype), encoding="utf-8")

    with (archetype_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    (archetype_dir / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    (archetype_dir / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    (archetype_dir / "archetype-prompt.md").write_text(archetype.persona_prompt, encoding="utf-8")

    return archetype_dir


def write_run_summary(run_dir: Path, verifications: list[dict], run_meta: dict) -> None:
    rows = ["| Arquétipo | Status | Turnos | Terminated_by | Bot score | Veredito |",
            "|---|---|---|---|---|---|"]
    for v in verifications:
        soft = v.get("soft_check", {}) or {}
        bot = soft.get("bot_score_1_10", "-")
        veredito = soft.get("veredito_curto", "-")
        rows.append(
            f"| {v.get('archetype_id')} - {v.get('archetype_slug')} | {v.get('status')} | "
            f"{v.get('turns_count')} | {v.get('terminated_by')} | {bot} | {veredito} |"
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

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_rehearsal_logger.py -v 2>&1 | tail -10
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rehearsal/logger.py backend/tests/test_rehearsal_logger.py
git commit -m "feat(rehearsal): logger de artefatos (transcript/events/verification)"
```

---

## Task 2.6: Rehearsal Runner (orquestrador principal)

**Files:**
- Create: `backend/scripts/rehearsal_runner.py`

Este é o script de entrypoint. Não terá teste unitário automatizado — será validado via smoke run na Task 4.1. A justificativa: é 90% I/O coordenação (HTTP, Redis, Supabase, filesystem), e o tempo gasto mockando tudo não compensa comparado a um smoke test real rápido.

- [ ] **Step 1: Implementar runner**

Em `backend/scripts/rehearsal_runner.py`:

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

# Load .env.local before importing backend modules that depend on env
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from app.config import settings  # noqa: E402
from scripts.rehearsal import supabase_io, logger as rlogger, gemini_actor, verifier  # noqa: E402
from scripts.rehearsal.archetypes import ALL_ARCHETYPES, Archetype  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("rehearsal")

DEV_BACKEND_URL = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
REHEARSAL_PHONE = os.environ.get("REHEARSAL_PHONE", "").strip()
MAX_TURNS = int(os.environ.get("REHEARSAL_MAX_TURNS", "20"))
TURN_TIMEOUT = float(os.environ.get("REHEARSAL_TURN_TIMEOUT", "15"))
POLL_INTERVAL = 0.5
OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "superpowers" / "plans" / "pilot" / "rehearsal-runs"

FINAL_STAGES = {"A1": "atacado", "A2": "private_label", "A3": None, "A4": "atacado", "A5": "exportacao"}


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _utc_ts_path_component() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


async def _health_check(client: httpx.AsyncClient) -> None:
    try:
        r = await client.get(f"{DEV_BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        log.info(f"Dev backend health OK ({DEV_BACKEND_URL})")
    except Exception as e:
        log.error(f"Dev backend health check failed: {e}")
        raise SystemExit(f"Dev backend em {DEV_BACKEND_URL} nao respondeu. Subir com REHEARSAL_MODE=true antes.")


def _build_meta_payload(phone: str, text: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "rehearsal",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "rehearsal", "display_phone_number": phone},
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


async def _send_user_message(client: httpx.AsyncClient, phone: str, text: str) -> None:
    payload = _build_meta_payload(phone, text)
    r = await client.post(f"{DEV_BACKEND_URL}/webhook/meta", json=payload, timeout=10)
    if r.status_code >= 400:
        log.warning(f"Webhook POST retornou {r.status_code}: {r.text[:200]}")


def _extract_stage_from_event(content: str) -> str | None:
    """Parse strings like 'Stage alterado para: atacado'."""
    marker = "stage alterado para"
    low = content.lower()
    if marker in low:
        after = content[low.index(marker) + len(marker):].strip(": ,.")
        return after.split()[0].strip().lower() if after else None
    return None


def _terminated(archetype: Archetype, events: list[dict], turns: int) -> str | None:
    """Return a termination reason or None to continue."""
    if turns >= MAX_TURNS:
        return "max_turns"
    for ev in events:
        content = ev.get("content", "").lower()
        if "encaminhado para" in content:
            return "encaminhar_humano"
    final_stage = FINAL_STAGES.get(archetype.id)
    if final_stage:
        for ev in events:
            stage = _extract_stage_from_event(ev.get("content", ""))
            if stage == final_stage:
                return "stage_reached"
    return None


async def _run_archetype(
    archetype: Archetype,
    client: httpx.AsyncClient,
    redis,
    run_dir: Path,
) -> dict:
    log.info(f"=== Iniciando arquetipo {archetype.id} ({archetype.slug}) ===")

    # 1. Wipe completo
    supabase_io.wipe_lead(REHEARSAL_PHONE)
    await supabase_io.wipe_redis_buffer(REHEARSAL_PHONE, redis)

    # 2. Enviar primeira mensagem
    start_iso = _now_iso()
    await _send_user_message(client, REHEARSAL_PHONE, archetype.first_message)

    # 3. Aguardar o lead ser criado (e depois buscar seu id)
    lead_id: str | None = None
    deadline = time.time() + TURN_TIMEOUT
    while time.time() < deadline and lead_id is None:
        await asyncio.sleep(POLL_INTERVAL)
        lead = supabase_io.get_lead_by_phone(REHEARSAL_PHONE)
        if lead:
            lead_id = lead["id"]
            break

    if not lead_id:
        log.error(f"{archetype.id}: lead nao foi criado em {TURN_TIMEOUT}s — abortando arquetipo")
        return {"archetype_id": archetype.id, "archetype_slug": archetype.slug,
                "status": "error", "error": "lead_not_created", "turns_count": 0,
                "terminated_by": "error", "soft_check": {}, "hard_checks": [],
                "stages_visited": []}

    # 4. Loop conversacional
    turns = 1  # conta o primeiro envio
    last_poll_iso = start_iso
    consecutive_timeouts = 0
    stages_visited: set[str] = set()
    terminated_by: str | None = None

    while True:
        # Poll por novas mensagens
        valeria_msgs = []
        poll_deadline = time.time() + TURN_TIMEOUT
        while time.time() < poll_deadline:
            new_msgs = supabase_io.get_messages_since(lead_id, last_poll_iso)
            valeria_msgs = [m for m in new_msgs if m.get("role") == "assistant"]
            # Atualiza stages visitados a partir de todos os messages (role system inclui stage changes)
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
            log.warning(f"{archetype.id}: turno {turns} sem resposta (timeout #{consecutive_timeouts})")
            if consecutive_timeouts >= 2:
                terminated_by = "timeout"
                break
        else:
            consecutive_timeouts = 0

        # Checar eventos atuais pra decidir se encerra
        events = supabase_io.get_system_events(lead_id)
        reason = _terminated(archetype, events, turns)
        if reason:
            terminated_by = reason
            break

        # Gerar proxima fala do lead com Gemini
        all_msgs = supabase_io.get_all_messages(lead_id)
        last_assistant = valeria_msgs[-1]["content"] if valeria_msgs else ""
        try:
            next_user_msg = gemini_actor.generate_next_lead_message(
                persona_prompt=archetype.persona_prompt,
                conversation_history=[{"role": m["role"], "content": m["content"]} for m in all_msgs],
                last_assistant_message=last_assistant,
            )
        except gemini_actor.GeminiFailure as e:
            log.error(f"{archetype.id}: Gemini falhou — {e}")
            terminated_by = "gemini_error"
            break

        if not next_user_msg:
            log.warning(f"{archetype.id}: Gemini retornou vazio — encerrando")
            terminated_by = "empty_gemini"
            break

        log.info(f"{archetype.id} turno {turns + 1} — Lead: {next_user_msg[:80]}")
        await _send_user_message(client, REHEARSAL_PHONE, next_user_msg)
        turns += 1

        if turns >= MAX_TURNS:
            terminated_by = "max_turns"
            break

    # 5. Verificacao
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

    # 6. Salvar artefatos
    rlogger.write_archetype_artifacts(
        run_dir=run_dir,
        archetype=archetype,
        messages=all_messages,
        events=events,
        verification=verification,
    )

    log.info(f"=== {archetype.id} finalizado: status={verification['status']} turns={turns} by={terminated_by} ===")
    return verification


def _render_inline(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = m.get("role", "?")
        label = {"user": "Lead", "assistant": "Valeria", "system": "system"}.get(role, role)
        lines.append(f"[{label}] {m.get('content', '')}")
    return "\n".join(lines)


async def main():
    if not REHEARSAL_PHONE:
        raise SystemExit("REHEARSAL_PHONE nao definido em .env.local")
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY nao definido em .env.local")

    only = os.environ.get("REHEARSAL_ONLY")  # ex: "A1" pra rodar so um
    archetypes = [a for a in ALL_ARCHETYPES if (not only or a.id == only)]
    if not archetypes:
        raise SystemExit(f"Nenhum arquetipo encontrado com REHEARSAL_ONLY={only}")

    run_ts = _utc_ts_path_component()
    run_dir = OUTPUT_ROOT / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Run dir: {run_dir}")

    started_at = _now_iso()
    run_meta = {
        "started_at": started_at,
        "git_sha": _git_sha(),
        "archetypes": [a.id for a in archetypes],
        "dev_backend_url": DEV_BACKEND_URL,
        "rehearsal_phone": REHEARSAL_PHONE,
        "gemini_model": gemini_actor.MODEL_NAME,
    }

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    verifications: list[dict] = []

    async with httpx.AsyncClient() as client:
        await _health_check(client)
        for archetype in archetypes:
            try:
                v = await _run_archetype(archetype, client, redis, run_dir)
            except Exception as e:
                log.exception(f"Erro catastrofico em {archetype.id}")
                v = {"archetype_id": archetype.id, "archetype_slug": archetype.slug,
                     "status": "error", "error": str(e), "turns_count": 0,
                     "terminated_by": "crash", "hard_checks": [], "soft_check": {},
                     "stages_visited": []}
            verifications.append(v)
            # Escreve summary incremental a cada arquetipo pra nao perder progresso
            rlogger.write_run_summary(run_dir, verifications, {**run_meta, "finished_at": _now_iso()})

    await redis.close()

    log.info(f"Run completo. Artefatos em: {run_dir}")
    # Exit code != 0 se algum arquetipo falhou — util pra CI futuro
    any_fail = any(v.get("status") != "passed" for v in verifications)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Validar imports**

```bash
cd backend && python -c "from scripts.rehearsal_runner import main; print('ok')"
```

Expected: `ok` (assumindo que as dependências `httpx`, `redis`, `dotenv` já estão no requirements — se falhar, a Task 3.1 adiciona).

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/rehearsal_runner.py
git commit -m "feat(rehearsal): runner principal que orquestra os 5 arquetipos"
```

---

## Task 3.1: Configuração (deps + env + VS Code task)

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example` (criar se não existir)
- Modify: `.vscode/tasks.json` (se existir; criar se não)

- [ ] **Step 1: Adicionar dependência ao `requirements.txt`**

Ler o arquivo atual:

```bash
cat "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/backend/requirements.txt"
```

Adicionar no final (se não estiver presente):

```
google-generativeai>=0.8.0
python-dotenv>=1.0.0
```

(se `python-dotenv` já estiver listado, não duplicar).

- [ ] **Step 2: Instalar dependências**

```bash
cd backend && pip install -r requirements.txt 2>&1 | tail -5
```

Expected: sucesso.

- [ ] **Step 3: Atualizar `.env.example` (sem secrets reais)**

Ler o atual:

```bash
cat "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/backend/.env.example" 2>/dev/null || echo "(arquivo nao existe)"
```

Adicionar ao final (ou criar se não existir) — se já existirem os SUPABASE/REDIS, não duplicar:

```
# === Rehearsal automatico (uso local apenas) ===
# Quando =true, backend substitui provider de WhatsApp por MockProvider (sem envio real)
REHEARSAL_MODE=false
# Numero usado nos arquetipos de rehearsal (deve estar na whitelist dev:phone_routes em Redis)
REHEARSAL_PHONE=
# Google AI Studio API key para Gemini 2.5 Pro
GEMINI_API_KEY=
# URL do backend dev onde o webhook do rehearsal bate
DEV_BACKEND_URL=http://127.0.0.1:8001
# Timeout por turno (segundos) e limite de turnos por arquetipo
REHEARSAL_TURN_TIMEOUT=15
REHEARSAL_MAX_TURNS=20
```

- [ ] **Step 4: Adicionar task no VS Code (se `.vscode/tasks.json` existir)**

```bash
ls "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/.vscode/tasks.json" 2>&1
```

Se existir, abrir e ler. Adicionar ao array `tasks`:

```json
{
  "label": "Run Rehearsal (all archetypes)",
  "type": "shell",
  "command": "python",
  "args": ["-m", "scripts.rehearsal_runner"],
  "options": {
    "cwd": "${workspaceFolder}/backend",
    "env": {
      "REHEARSAL_MODE": "true"
    }
  },
  "problemMatcher": [],
  "presentation": {
    "reveal": "always",
    "panel": "dedicated"
  }
}
```

Se NÃO existir `.vscode/tasks.json`, pular este passo (não criar o arquivo só pra isso — o usuário prefere shell direto).

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/.env.example .vscode/tasks.json 2>/dev/null
git commit -m "chore(rehearsal): adicionar google-generativeai + variaveis de env + VS Code task"
```

(Se `.vscode/tasks.json` não foi modificado, o `git add` dele falha silenciosamente — OK.)

---

## Task 4.1: Smoke test end-to-end com arquétipo A1

**Files:** nenhum novo — este é um teste manual assistido.

**Pré-requisitos manuais (fora do escopo do subagente — usuário executa):**
1. Preencher `.env.local` com `GEMINI_API_KEY` real e `REHEARSAL_PHONE=5534996652412`.
2. Subir o backend dev com `REHEARSAL_MODE=true`.

Depois:

- [ ] **Step 1: Verificar que a flag está ativa no backend dev**

```bash
curl -s http://127.0.0.1:8001/health | head -5
```

Expected: 200 OK.

- [ ] **Step 2: Rodar só o A1**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/backend"
REHEARSAL_ONLY=A1 python -m scripts.rehearsal_runner 2>&1 | tee /tmp/rehearsal-smoke.log
```

Expected: logs informando wipe, turnos, e finalizando com artefatos salvos.

- [ ] **Step 3: Verificar artefatos criados**

```bash
ls "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/docs/superpowers/plans/pilot/rehearsal-runs/"
```

Expected: pasta `<timestamp>/A1-cafeteria-atacado/` com `transcript.md`, `events.jsonl`, `messages.json`, `verification.json`, `archetype-prompt.md`.

- [ ] **Step 4: Revisar transcript.md visualmente**

```bash
cat "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal/docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/A1-cafeteria-atacado/transcript.md"
```

Validar subjetivamente:
- Lead (Gemini) soa como dono de cafeteria BH? Pergunta preço?
- Valéria chegou em stage atacado?
- A conversa termina de forma plausível (encaminhar_humano ou max turnos)?

- [ ] **Step 5: Checar verification.json**

```bash
cat "<path>/A1-cafeteria-atacado/verification.json"
```

Expected: campos `status`, `hard_checks`, `soft_check`, `turns_count`, `terminated_by` todos presentes. `soft_check.bot_score_1_10` deve ser um inteiro.

- [ ] **Step 6: Se tudo OK, commit do primeiro run como artefato de referência (opcional)**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/.worktrees/valeria-rehearsal"
git add docs/superpowers/plans/pilot/rehearsal-runs/
git commit -m "docs(rehearsal): primeiro smoke run A1 como baseline"
```

Se houve bug detectado: PARAR, descrever o bug, e voltar pra task que precisa de fix. Não tentar consertar "de um jeito rápido" durante o smoke.

---

## Verificação end-to-end

1. **Testes unitários passam:** `cd backend && python -m pytest tests/ -q` — tudo verde (≥10 testes novos + os existentes).
2. **Smoke A1 funciona:** Task 4.1 produz artefatos e o transcript é plausível.
3. **Smoke A1-A5 funciona:** repetir Task 4.1 sem `REHEARSAL_ONLY` — os 5 arquétipos rodam em sequência, cada um com pasta própria, `summary.md` consolidado ao final.

Se o smoke A1 passa mas o run completo falha em algum arquétipo, isso é **esperado** — o ponto do rehearsal é justamente expor gaps da Valéria. O teste de aceitação é "o script roda até o fim, cada arquétipo fica com seu veredicto", não "todos os 5 passam".

---

## Arquivos críticos (referência pós-implementação)

- `backend/app/whatsapp/mock_provider.py` — interface completa do provider, mock-only.
- `backend/app/whatsapp/registry.py:get_provider` — ponto onde o toggle acontece.
- `backend/scripts/rehearsal_runner.py:main` — entrypoint. `_run_archetype` tem o loop conversacional.
- `backend/scripts/rehearsal/archetypes.py:ALL_ARCHETYPES` — adicionar/ajustar personas aqui.
- `backend/scripts/rehearsal/verifier.py:verify` — mudar critérios de "passou" aqui.
- `docs/superpowers/plans/pilot/rehearsal-runs/<ts>/` — onde os artefatos vão parar.

---

## O que este plano NÃO inclui (de propósito)

- Testes automatizados do `rehearsal_runner.py` em si (validado manualmente via smoke — justificativa na Task 2.6).
- Paralelização entre arquétipos (constraint do design).
- Dashboard web de resultados (análise é via `summary.md` por enquanto).
- Suporte a mensagens de áudio/imagem no lead simulado (MVP só texto).
- Integração com CI (smoke é manual por enquanto; o exit code != 0 já deixa isso preparado pra futuro).

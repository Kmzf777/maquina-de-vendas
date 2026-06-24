"""process_buffered_messages: mutex por lead + early typing — auditoria 5544991611703.

1. Dois runs concorrentes do MESMO lead são serializados pelo lead_run_lock: o 2º só
   roda run_agent depois que o 1º termina (o 2º vê o histórico já persistido).
2. O "digitando…" é disparado IMEDIATAMENTE (antes da 1ª bolha) quando há wamid.
"""
import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_lead():
    return {"id": "lead-mx-1", "phone": "+5544991611703", "stage": "secretaria",
            "status": "active", "ai_enabled": True, "name": "Arthur"}


def _make_channel():
    return {"id": "ch-mx-1", "is_active": True, "mode": "ai",
            "agent_profiles": {"id": "p1", "stages": {}},
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _make_conversation():
    return {"id": "conv-mx-1", "lead_id": "lead-mx-1", "channel_id": "ch-mx-1",
            "stage": "secretaria", "status": "active", "followup_enabled": True}


def _mock_settings():
    s = MagicMock()
    s.ai_phone_number_id = None
    s.ai_phone_number_ids = frozenset()
    return s


def _sb_mock():
    return MagicMock(table=MagicMock(return_value=MagicMock(
        update=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(execute=MagicMock())))),
        select=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            single=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))))
        )))),
    )))


def _common_patches(provider, run_agent_fn):
    """Lista de patchers comuns aos dois testes (entram via ExitStack p/ evitar o
    limite de blocos aninhados do CPython num `with` gigante)."""
    P = "app.buffer.processor."
    return [
        patch(P + "get_or_create_lead", return_value=_make_lead()),
        patch(P + "get_channel_by_id", return_value=_make_channel()),
        patch(P + "get_provider", return_value=provider),
        patch(P + "get_or_create_conversation", return_value=_make_conversation()),
        patch(P + "get_active_enrollment", return_value=None),
        patch(P + "save_message"),
        patch(P + "_save_with_retry", new=AsyncMock()),
        patch(P + "run_agent", side_effect=run_agent_fn),
        patch(P + "_is_recent_duplicate", return_value=False),
        patch(P + "_wamid_already_processed", return_value=False),
        patch(P + "update_conversation"),
        patch(P + "_schedule_followup"),
        patch(P + "pop_interest_marked", return_value=None),
        patch(P + "pop_deferred_media", return_value=[]),
        # Zera o pacing de bolha (delay real ~5s do 1º balão) p/ não lentificar o teste —
        # é o sleep PÓS-run, independente do pulso de early-typing.
        patch(P + "_sleep_with_typing_renewal", new=AsyncMock()),
        patch(P + "get_supabase", return_value=_sb_mock()),
        patch(P + "run_with_retry"),
        patch(P + "settings", _mock_settings()),
        patch(P + "_check_frustration_guardrail", return_value=False),
        patch(P + "_update_last_msg"),
    ]


@pytest.mark.asyncio
async def test_concurrent_runs_same_lead_are_serialized():
    """RUN 2 não pode entrar em run_agent enquanto RUN 1 ainda processa o mesmo lead."""
    events: list[str] = []
    active = {"n": 0}

    async def fake_run_agent(conversation, text, **kwargs):
        active["n"] += 1
        assert active["n"] == 1, "dois run_agent concorrentes para o mesmo lead!"
        events.append(f"start:{text}")
        await asyncio.sleep(0.15)
        events.append(f"end:{text}")
        active["n"] -= 1
        return f"resposta para {text}"

    from app.buffer import lead_lock

    class _FakeLockRedis:
        def __init__(self): self.store = {}
        async def set(self, k, v, nx=False, ex=None):
            if nx and k in self.store: return None
            self.store[k] = v; return True
        async def eval(self, script, n, k, tok):
            if self.store.get(k) == tok: self.store.pop(k, None); return 1
            return 0
    shared = _FakeLockRedis()

    provider = AsyncMock(send_text=AsyncMock(return_value={}))

    with ExitStack() as stack:
        for p in _common_patches(provider, fake_run_agent):
            stack.enter_context(p)
        stack.enter_context(patch.object(lead_lock, "_unavailable_until", 0.0))
        stack.enter_context(patch.object(lead_lock, "LOCK_POLL_INTERVAL", 0.02))
        stack.enter_context(patch.object(lead_lock, "_get_client", lambda: shared))

        from app.buffer.processor import process_buffered_messages
        await asyncio.gather(
            process_buffered_messages("+5544991611703", "msg um", "ch-mx-1"),
            process_buffered_messages("+5544991611703", "msg dois", "ch-mx-1"),
        )

    assert events[0].startswith("start:") and events[1].startswith("end:")
    assert events[2].startswith("start:") and events[3].startswith("end:")
    assert events[0].split(":")[1] == events[1].split(":")[1]  # par start/end do mesmo texto


@pytest.mark.asyncio
async def test_early_typing_fired_before_first_bubble():
    """Com wamid presente, o 'digitando…' dispara durante o processamento (antes da bolha)."""
    typing_calls: list[str] = []

    async def fake_run_agent(conversation, text, **kwargs):
        await asyncio.sleep(0.05)
        return "oi"

    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={})

    async def _typing(wamid):
        typing_calls.append(wamid)
        return {}
    provider.send_typing_indicator = AsyncMock(side_effect=_typing)

    # Lock hermético/rápido (não depende de Redis real neste teste de typing).
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_lock(lead_id):
        yield True

    with ExitStack() as stack:
        for p in _common_patches(provider, fake_run_agent):
            stack.enter_context(p)
        stack.enter_context(patch("app.buffer.processor.lead_run_lock", _noop_lock))

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5544991611703", "ola", "ch-mx-1", wamid="wamid.ABC")

    assert "wamid.ABC" in typing_calls

"""Re-coalescing (aglutinação) por lead — auditoria 5533999429785 (2026-06-25).

Cenário forense: o cliente mandou uma imagem e, ~16s depois, um texto. O lock serializou
os dois turnos (correto), mas como NÃO havia aglutinação, a Valéria respondeu DOIS blocos
empilhados e contraditórios (um pedindo "qual café te chamou", outro já em private_label).

Duas defesas, ambas via _has_newer_inbound (watermark = created_at do inbound que
engatilhou o worker):

1. STALE WORKER ABORT (pós-lock): ao adquirir o lock, se já existe inbound do cliente mais
   novo que o deste worker, aborta em silêncio — um worker posterior (já na fila) responde
   o contexto COMPLETO numa única resposta. Cobre a pilha de mensagens enfileiradas.

2. IN-FLIGHT GUARD (cauda do lock): se o cliente fala DURANTE o envio das bolhas, paramos
   de despejar o resto deste turno (bolhas restantes + mídia diferida) — o worker posterior
   responde holisticamente. Otimiza a cauda do lock exatamente quando empilharia.
"""
import asyncio
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_lead():
    return {"id": "lead-rc-1", "phone": "+5533999429785", "stage": "atacado",
            "status": "active", "ai_enabled": True, "name": "Neimara"}


def _make_channel():
    return {"id": "ch-rc-1", "is_active": True, "mode": "ai",
            "agent_profiles": {"id": "p1", "stages": {}},
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _make_conversation():
    return {"id": "conv-rc-1", "lead_id": "lead-rc-1", "channel_id": "ch-rc-1",
            "stage": "atacado", "status": "active", "followup_enabled": True}


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


@asynccontextmanager
async def _noop_lock(lead_id):
    yield True


def _common_patches(provider, run_agent_fn, has_newer, deferred_media):
    P = "app.buffer.processor."
    # _save_with_retry devolve o registro do inbound com created_at (watermark do turno).
    saved_user = {"id": "umsg-rc-1", "created_at": "2026-06-25T17:51:45.887+00:00"}
    return [
        patch(P + "get_or_create_lead", return_value=_make_lead()),
        patch(P + "get_channel_by_id", return_value=_make_channel()),
        patch(P + "get_provider", return_value=provider),
        patch(P + "get_or_create_conversation", return_value=_make_conversation()),
        patch(P + "get_active_enrollment", return_value=None),
        patch(P + "save_message"),
        patch(P + "_save_with_retry", new=AsyncMock(return_value=saved_user)),
        patch(P + "run_agent", side_effect=run_agent_fn),
        patch(P + "_is_recent_duplicate", return_value=False),
        patch(P + "_wamid_already_processed", return_value=False),
        patch(P + "update_conversation"),
        patch(P + "_schedule_followup"),
        patch(P + "pop_interest_marked", return_value=None),
        patch(P + "pop_deferred_media", return_value=list(deferred_media)),
        patch(P + "_sleep_with_typing_renewal", new=AsyncMock()),
        patch(P + "_ai_still_enabled", return_value=True),
        patch(P + "_has_newer_inbound", side_effect=has_newer),
        patch(P + "get_supabase", return_value=_sb_mock()),
        patch(P + "run_with_retry"),
        patch(P + "settings", _mock_settings()),
        patch(P + "_check_frustration_guardrail", return_value=False),
        patch(P + "_update_last_msg"),
        patch(P + "lead_run_lock", _noop_lock),
    ]


@pytest.mark.asyncio
async def test_stale_worker_aborts_when_newer_inbound_after_lock():
    """Pós-lock: inbound mais novo já presente → aborta SEM chamar run_agent nem enviar."""
    run_calls: list[str] = []

    async def fake_run_agent(conversation, text, **kwargs):
        run_calls.append(text)
        return "nao deveria rodar"

    provider = AsyncMock(send_text=AsyncMock(return_value={}))

    with ExitStack() as stack:
        # 1ª (e única) checagem = pós-lock → True ⇒ aborta.
        for p in _common_patches(provider, fake_run_agent, has_newer=[True], deferred_media=[]):
            stack.enter_context(p)
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5533999429785", "Eu pensei em uma dessas logos", "ch-rc-1")

    assert run_calls == [], "worker stale NÃO pode chamar run_agent"
    provider.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_normal_turn_runs_when_no_newer_inbound():
    """Sem inbound mais novo → fluxo normal: run_agent roda e a bolha é enviada."""
    run_calls: list[str] = []

    async def fake_run_agent(conversation, text, **kwargs):
        run_calls.append(text)
        return "resposta unica"

    provider = AsyncMock(send_text=AsyncMock(return_value={}))

    with ExitStack() as stack:
        # Sempre False (pós-lock + qualquer checagem in-flight).
        for p in _common_patches(provider, fake_run_agent, has_newer=lambda *a, **k: False, deferred_media=[]):
            stack.enter_context(p)
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5533999429785", "oi", "ch-rc-1")

    assert run_calls == ["oi"]
    provider.send_text.assert_awaited()


@pytest.mark.asyncio
async def test_in_flight_guard_stops_remaining_bubbles_and_drains_media():
    """In-flight: cliente fala no meio do envio → para as bolhas restantes e DESCARTA mídia."""
    async def fake_run_agent(conversation, text, **kwargs):
        return "bloco longo"

    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={})
    provider.send_image_base64 = AsyncMock(return_value={})

    deferred = [{"b64": "AAAA", "mimetype": "image/png", "caption": "Classico"}]

    with ExitStack() as stack:
        # Sequência de _has_newer_inbound:
        #   #1 pós-lock = False (segue)
        #   #2 antes da bolha 1 = False (envia b1)
        #   #3 antes da bolha 2 = True (aborta resto)
        for p in _common_patches(
            provider, fake_run_agent, has_newer=[False, False, True], deferred_media=deferred
        ):
            stack.enter_context(p)
        stack.enter_context(patch("app.buffer.processor.split_into_bubbles",
                                  return_value=["b1", "b2", "b3"]))
        pop_dm = stack.enter_context(
            patch("app.buffer.processor.pop_deferred_media", return_value=list(deferred))
        )
        sched = stack.enter_context(patch("app.buffer.processor._schedule_followup"))

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5533999429785", "minha logo", "ch-rc-1")

    assert provider.send_text.await_count == 1, "só a 1ª bolha deve sair antes do abort"
    provider.send_image_base64.assert_not_called()  # mídia diferida NÃO é despejada
    assert pop_dm.called, "mídia diferida deve ser DRENADA (popada) para não vazar ao próximo turno"
    sched.assert_not_called()  # follow-up fica para o worker posterior


def test_has_newer_inbound_query_semantics():
    """_has_newer_inbound: True se há user msg mais nova; False sem watermark / vazio / erro."""
    from app.buffer import processor as proc

    def _sb_with(rows=None, raises=False):
        chain = MagicMock()
        if raises:
            chain.execute.side_effect = RuntimeError("db down")
        else:
            chain.execute.return_value = MagicMock(data=rows)
        for m in ("select", "eq", "gt", "limit"):
            setattr(chain, m, MagicMock(return_value=chain))
        return MagicMock(table=MagicMock(return_value=chain))

    wm = "2026-06-25T17:51:45.887+00:00"

    with patch.object(proc, "get_supabase", return_value=_sb_with(rows=[{"id": "x"}])):
        assert proc._has_newer_inbound("conv-rc-1", wm) is True
    with patch.object(proc, "get_supabase", return_value=_sb_with(rows=[])):
        assert proc._has_newer_inbound("conv-rc-1", wm) is False
    # Sem watermark → nunca aborta (não consulta o banco).
    with patch.object(proc, "get_supabase", return_value=_sb_with(rows=[{"id": "x"}])):
        assert proc._has_newer_inbound("conv-rc-1", None) is False
    # Erro de leitura → fail-open (False, não aborta às cegas).
    with patch.object(proc, "get_supabase", return_value=_sb_with(raises=True)):
        assert proc._has_newer_inbound("conv-rc-1", wm) is False

"""Regressão: respostas curtas repetidas com wamids distintos NÃO podem ser descartadas.

Cenário real (lead 5534932262600, 2026-06-16): o lead respondeu "sim" a duas perguntas
consecutivas (<15s), com wamids distintos. O dedup por conteúdo+tempo (_is_recent_duplicate)
descartou a 2ª como "duplicata" e a IA parou. Correção: o dedup por conteúdo só vale quando
NÃO há wamid — com wamid, os layers por wamid (Redis SETNX + _wamid_already_processed) são a
autoridade.
"""
from contextlib import ExitStack
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.buffer import processor


def _patch_pipeline(stack: ExitStack, *, dedup_result: bool) -> dict:
    """Mocka o mínimo de process_buffered_messages para parar no early-return do canal humano.

    Canal mode='human' faz a função salvar a mensagem do user e retornar ANTES do agente —
    o que nos basta: queremos provar que a 2ª mensagem é SALVA (processada), não engolida.
    """
    lead = {"id": "L1", "phone": "5534932262600", "wa_id": "553432262600",
            "ai_enabled": True, "metadata": {}}
    channel = {"id": "ch1", "mode": "human", "provider_config": {}}
    conv = {"id": "conv1", "status": "active", "stage": "atacado", "followup_enabled": False}

    p = lambda name, *args, **kw: stack.enter_context(patch.object(processor, name, *args, **kw))

    p("get_or_create_lead", return_value=lead)
    p("get_channel_by_id", return_value=channel)
    p("get_or_create_conversation", return_value=conv)
    p("get_provider", return_value=MagicMock())
    p("update_conversation", MagicMock())
    p("get_supabase", MagicMock())
    p("run_with_retry", MagicMock(return_value=MagicMock(data={"unread_count": 0})))
    p("_resolve_media", new=AsyncMock(return_value=("sim", None, None, None, None)))
    p("_wamid_already_processed", return_value=False)
    save_message = p("save_message", MagicMock())
    is_recent_dup = p("_is_recent_duplicate", return_value=dedup_result)

    # Efeitos colaterais best-effort (lazy imports) — neutralizados p/ não tocar rede.
    stack.enter_context(patch("app.broadcast.service.record_broadcast_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_campaign_reply", MagicMock()))
    stack.enter_context(patch("app.automation.triggers.fire_trigger", new=AsyncMock()))

    return {"save_message": save_message, "is_recent_dup": is_recent_dup}


def _user_save_count(save_message_mock: MagicMock) -> int:
    """Quantas vezes save_message foi chamado com role='user' (3º arg posicional)."""
    return sum(
        1 for c in save_message_mock.call_args_list
        if len(c.args) >= 3 and c.args[2] == "user"
    )


@pytest.mark.asyncio
async def test_dois_sim_com_wamids_distintos_sao_ambos_processados():
    """Dois 'sim' (<15s) com wamids DISTINTOS → ambos salvos, mesmo que o dedup de conteúdo flague."""
    with ExitStack() as stack:
        # dedup_result=True simula que _is_recent_duplicate ACHARIA duplicata — não pode importar.
        mocks = _patch_pipeline(stack, dedup_result=True)

        await processor.process_buffered_messages(
            "5534932262600", "sim", channel_id="ch1", wamid="wamid.PRIMEIRO_SIM",
        )
        await processor.process_buffered_messages(
            "5534932262600", "sim", channel_id="ch1", wamid="wamid.SEGUNDO_SIM",
        )

        assert _user_save_count(mocks["save_message"]) == 2, (
            "ambas as mensagens 'sim' (wamids distintos) devem ser salvas"
        )
        # Com wamid presente, o dedup por conteúdo nem é consultado (curto-circuito).
        mocks["is_recent_dup"].assert_not_called()


@pytest.mark.asyncio
async def test_sem_wamid_o_dedup_de_conteudo_ainda_protege():
    """Sem wamid (provider sem id), o dedup por conteúdo permanece como rede de segurança."""
    with ExitStack() as stack:
        mocks = _patch_pipeline(stack, dedup_result=True)

        await processor.process_buffered_messages(
            "5534932262600", "sim", channel_id="ch1", wamid="",  # sem wamid
        )

        # Mensagem descartada como duplicata → NÃO salva; e o dedup FOI consultado.
        assert _user_save_count(mocks["save_message"]) == 0
        mocks["is_recent_dup"].assert_called_once()

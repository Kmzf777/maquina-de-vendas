"""Gate de autoresponder no processor — o caso Letícia (2026-07-08).

O número dela é o bot da gelateria Duo Gelatto: o auto-reply com links de iFood
foi tratado como fala humana, caiu no fallback de LLM-down e virou handoff pro
João (que ainda mandou follow-up pro robô). O gate corta isso ANTES do agente:
1º hit → uma única sondagem humana; 2º hit → silêncio + nota analítica.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.buffer import processor

GELATO_AUTOREPLY = (
    "‎Duo Gelatto Nova Era agradece seu contato. \n\n"
    "Para entrega acesse os links abaixo:\n\n"
    "https://www.ifood.com.br/delivery/a\nhttps://www.ifood.com.br/delivery/b\n"
    "Para outros assuntos, continue por aqui."
)


def _provider():
    p = MagicMock()
    p.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.PROBE"}]})
    return p


@pytest.mark.asyncio
async def test_primeiro_hit_envia_sondagem_unica(monkeypatch):
    from app.leads import service as leads_service

    updates = {}
    monkeypatch.setattr(
        leads_service, "update_lead",
        lambda lid, **f: updates.update({lid: f}) or {"id": lid},
    )
    saved = []
    monkeypatch.setattr(processor, "save_message", lambda *a, **k: saved.append((a, k)) or {"id": "m1"})

    provider = _provider()
    lead = {"id": "L-leticia", "metadata": None}
    handled = await processor._handle_autoresponder(
        lead, "5562998354407", {"id": "c1", "stage": "secretaria"}, provider, GELATO_AUTOREPLY,
    )

    assert handled is True
    provider.send_text.assert_awaited_once()
    assert updates["L-leticia"]["metadata"]["autoresponder_hits"] == 1


@pytest.mark.asyncio
async def test_segundo_hit_silencia_sem_sondar(monkeypatch):
    from app.leads import service as leads_service

    updates = {}
    monkeypatch.setattr(
        leads_service, "update_lead",
        lambda lid, **f: updates.update({lid: f}) or {"id": lid},
    )
    monkeypatch.setattr(processor, "save_message", lambda *a, **k: {"id": "m1"})
    monkeypatch.setattr(processor, "get_supabase", lambda: MagicMock())

    provider = _provider()
    lead = {"id": "L-leticia", "metadata": {"autoresponder_hits": 1}}
    handled = await processor._handle_autoresponder(
        lead, "5562998354407", {"id": "c1", "stage": "secretaria"}, provider, GELATO_AUTOREPLY,
    )

    assert handled is True
    provider.send_text.assert_not_awaited()
    assert updates["L-leticia"]["metadata"]["autoresponder_hits"] == 2


@pytest.mark.asyncio
async def test_texto_humano_nao_e_tratado(monkeypatch):
    provider = _provider()
    handled = await processor._handle_autoresponder(
        {"id": "L1", "metadata": None}, "5534999", {"id": "c1", "stage": "secretaria"}, provider, "Sim",
    )
    assert handled is False
    provider.send_text.assert_not_awaited()

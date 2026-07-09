"""TDD: verdade-no-marcador da mídia diferida (auditoria Wander 5567999295671, 08/07).

Caso real: turno da reação 👍🏽 chamou enviar_fotos (4 fotos enfileiradas) e gravou
"[enviar_fotos] Fotos de private_label enviadas (4/4)" NO ENFILEIRAMENTO; o inbound
"Sim / Quero ver as fotos" chegou durante o pacing → [RECOALESCE] superseded → a fila
foi DRENADA sem enviar (zero requests de mídia no meta_webhook_logs), mas o marcador
mentiroso ficou no histórico. O dedup da tool passou a recusar reenvio para sempre e o
modelo "gaslightou" o lead ("as fotos já foram enviadas aqui no chat"), prometeu
reenviar sem conseguir, e o lead foi ao handoff com "Não chegou nada".

Correção: o marcador de entrega (e o carimbo metadata.catalog_shown) só nascem APÓS o
envio real, no processor (_dispatch_deferred_media → record_deferred_media_delivery),
com contagem honesta (k/n). Fila drenada = sem marcador = reenvio possível no próximo
turno. Dedup intra-turno passa a ser feito pela própria fila.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import app.agent.tools as tools
from app.agent.tools import _deferred_media


def _clean_queue(conv_id):
    _deferred_media.pop(conv_id, None)


# ---------------------------------------------------------------------------
# Camada tool (enfileiramento): nada de marcador nem catalog_shown antes da entrega
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enviar_fotos_enfileira_sem_gravar_marcador():
    """No enfileiramento NÃO se grava o marcador de entrega nem catalog_shown."""
    conv_id = "conv-truth-1"
    _clean_queue(conv_id)

    with patch.object(tools, "get_history", return_value=[]), \
         patch.object(tools, "save_message") as m_save, \
         patch.object(tools, "get_lead", return_value={"id": "lead-1", "metadata": {}}), \
         patch.object(tools, "update_lead") as m_upd:
        result = await tools.execute_tool(
            "enviar_fotos", {"categoria": "private_label"},
            lead_id="lead-1", phone="5567999295671", conversation_id=conv_id,
        )

    try:
        assert "enfileirada" in result.lower()
        # O marcador de entrega não pode nascer aqui — só após o envio real.
        for call in m_save.call_args_list:
            joined = " ".join(str(a) for a in call.args) + str(call.kwargs)
            assert "[enviar_fotos]" not in joined
        m_upd.assert_not_called()
        queue = _deferred_media.get(conv_id) or []
        assert len(queue) == 4
        for item in queue:
            assert item["marker"] == "[enviar_fotos] Fotos de private_label enviadas"
            assert item["catalog"] is True
            assert item["b64"] and item["mimetype"]
    finally:
        _clean_queue(conv_id)


@pytest.mark.asyncio
async def test_enviar_fotos_dedup_intra_turno_pela_fila():
    """Segunda chamada no MESMO turno não duplica a fila (dedup migrou p/ a fila)."""
    conv_id = "conv-truth-2"
    _clean_queue(conv_id)
    _deferred_media[conv_id] = [{
        "b64": "x", "mimetype": "image/jpeg", "caption": "",
        "marker": "[enviar_fotos] Fotos de private_label enviadas", "catalog": True,
    }]

    with patch.object(tools, "get_history", return_value=[]), \
         patch.object(tools, "save_message") as m_save:
        result = await tools.execute_tool(
            "enviar_fotos", {"categoria": "private_label"},
            lead_id="lead-1", phone="5567999295671", conversation_id=conv_id,
        )

    try:
        assert "ja enfileirad" in result.lower() or "já enfileirad" in result.lower()
        assert len(_deferred_media[conv_id]) == 1
        m_save.assert_not_called()
    finally:
        _clean_queue(conv_id)


@pytest.mark.asyncio
async def test_enviar_fotos_reenvio_possivel_apos_drain():
    """Cenário Wander: fila drenada por supersede (sem marcador no histórico) →
    a tool DEVE aceitar reenviar no turno seguinte (recuperação)."""
    conv_id = "conv-truth-3"
    _clean_queue(conv_id)  # fila drenada pelo pop do supersede

    # Histórico do turno seguinte: sem NENHUM marcador [enviar_fotos] (a correção
    # deixou de gravá-lo no enfileiramento).
    with patch.object(tools, "get_history", return_value=[
            {"role": "user", "content": "? Cadê as fotos"},
         ]), \
         patch.object(tools, "save_message"):
        result = await tools.execute_tool(
            "enviar_fotos", {"categoria": "private_label"},
            lead_id="lead-1", phone="5567999295671", conversation_id=conv_id,
        )

    try:
        assert "enfileirada" in result.lower()
        assert len(_deferred_media.get(conv_id) or []) == 4
    finally:
        _clean_queue(conv_id)


@pytest.mark.asyncio
async def test_enviar_fotos_guard_de_historico_continua_valendo():
    """Com marcador de ENTREGA REAL no histórico, o dedup continua recusando."""
    conv_id = "conv-truth-4"
    _clean_queue(conv_id)

    with patch.object(tools, "get_history", return_value=[
            {"role": "system", "content": "[enviar_fotos] Fotos de private_label enviadas (4/4)"},
         ]), \
         patch.object(tools, "save_message"):
        result = await tools.execute_tool(
            "enviar_fotos", {"categoria": "private_label"},
            lead_id="lead-1", phone="5567999295671", conversation_id=conv_id,
        )

    assert "nao reenviar" in result.lower()
    assert _deferred_media.get(conv_id) in (None, [])


@pytest.mark.asyncio
async def test_enviar_foto_produto_sem_marcador_no_enfileiramento(monkeypatch):
    """enviar_foto_produto segue o mesmo contrato: marcador só pós-entrega."""
    conv_id = "conv-truth-5"
    _clean_queue(conv_id)
    monkeypatch.setattr(tools, "PRODUTO_PHOTO_MAP", {
        "private_label": {"moedor": {"file": "foto_1.jpg", "caption": "moedor"}},
    })

    with patch.object(tools, "get_history", return_value=[]), \
         patch.object(tools, "save_message") as m_save:
        result = await tools.execute_tool(
            "enviar_foto_produto", {"categoria": "private_label", "produto": "Moedor"},
            lead_id="lead-1", phone="5567999295671", conversation_id=conv_id,
        )

    try:
        assert "enfileirada" in result.lower()
        m_save.assert_not_called()
        queue = _deferred_media.get(conv_id) or []
        assert len(queue) == 1
        assert queue[0]["marker"] == "[enviar_foto_produto] Foto de moedor enviada"
    finally:
        _clean_queue(conv_id)


# ---------------------------------------------------------------------------
# record_deferred_media_delivery: o marcador nasce da entrega real
# ---------------------------------------------------------------------------

def test_record_delivery_grava_marcador_e_catalogo():
    groups = [{"marker": "[enviar_fotos] Fotos de private_label enviadas",
               "sent": 4, "total": 4, "catalog": True}]
    with patch.object(tools, "save_message") as m_save, \
         patch.object(tools, "get_lead", return_value={"id": "lead-1", "metadata": {}}), \
         patch.object(tools, "update_lead") as m_upd:
        tools.record_deferred_media_delivery("lead-1", "conv-x", groups)

    m_save.assert_called_once()
    args, kwargs = m_save.call_args
    assert args[0] == "lead-1"
    assert args[1] == "system"
    assert args[2] == "[enviar_fotos] Fotos de private_label enviadas (4/4)"
    assert kwargs.get("conversation_id") == "conv-x"
    # catalog_shown só carimba com entrega real confirmada
    meta = m_upd.call_args.kwargs.get("metadata") or {}
    assert meta.get("catalog_shown") is True


def test_record_delivery_zero_entregue_nao_grava_nada():
    """Falha total de envio → sem marcador (reenvio possível) e sem catalog_shown."""
    groups = [{"marker": "[enviar_fotos] Fotos de private_label enviadas",
               "sent": 0, "total": 4, "catalog": True}]
    with patch.object(tools, "save_message") as m_save, \
         patch.object(tools, "update_lead") as m_upd:
        tools.record_deferred_media_delivery("lead-1", "conv-x", groups)

    m_save.assert_not_called()
    m_upd.assert_not_called()


def test_record_delivery_parcial_conta_honesto():
    groups = [{"marker": "[enviar_fotos] Fotos de private_label enviadas",
               "sent": 1, "total": 4, "catalog": True}]
    with patch.object(tools, "save_message") as m_save, \
         patch.object(tools, "get_lead", return_value={"id": "lead-1", "metadata": {}}), \
         patch.object(tools, "update_lead"):
        tools.record_deferred_media_delivery("lead-1", "conv-x", groups)

    assert m_save.call_args.args[2] == "[enviar_fotos] Fotos de private_label enviadas (1/4)"


# ---------------------------------------------------------------------------
# Camada processor: _dispatch_deferred_media envia e SÓ ENTÃO registra
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_envia_e_registra_pos_entrega():
    from app.buffer import processor as P
    conv_id = "conv-truth-6"
    _clean_queue(conv_id)
    _deferred_media[conv_id] = [
        {"b64": "a", "mimetype": "image/jpeg", "caption": "1",
         "marker": "[enviar_fotos] Fotos de private_label enviadas", "catalog": True},
        {"b64": "b", "mimetype": "image/jpeg", "caption": "2",
         "marker": "[enviar_fotos] Fotos de private_label enviadas", "catalog": True},
    ]
    provider = MagicMock()
    provider.send_image_base64 = AsyncMock()

    with patch.object(P, "record_deferred_media_delivery") as m_rec, \
         patch.object(P.asyncio, "sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(
            provider, "556799295671",
            {"id": conv_id}, {"id": "lead-1"},
        )

    assert provider.send_image_base64.await_count == 2
    m_rec.assert_called_once()
    groups = m_rec.call_args.args[2]
    assert groups == [{"marker": "[enviar_fotos] Fotos de private_label enviadas",
                       "sent": 2, "total": 2, "catalog": True}]
    assert _deferred_media.get(conv_id) in (None, [])


@pytest.mark.asyncio
async def test_dispatch_falha_parcial_registra_contagem_honesta():
    from app.buffer import processor as P
    conv_id = "conv-truth-7"
    _clean_queue(conv_id)
    _deferred_media[conv_id] = [
        {"b64": "a", "mimetype": "image/jpeg", "caption": "1",
         "marker": "[enviar_fotos] Fotos de private_label enviadas", "catalog": True},
        {"b64": "b", "mimetype": "image/jpeg", "caption": "2",
         "marker": "[enviar_fotos] Fotos de private_label enviadas", "catalog": True},
    ]
    provider = MagicMock()
    provider.send_image_base64 = AsyncMock(side_effect=[None, RuntimeError("meta down")])

    with patch.object(P, "record_deferred_media_delivery") as m_rec, \
         patch.object(P.asyncio, "sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(
            provider, "556799295671", {"id": conv_id}, {"id": "lead-1"},
        )

    groups = m_rec.call_args.args[2]
    assert groups[0]["sent"] == 1 and groups[0]["total"] == 2


@pytest.mark.asyncio
async def test_dispatch_fila_vazia_e_noop():
    """Pós-drain (supersede/handoff) a fila está vazia: nada é enviado nem registrado."""
    from app.buffer import processor as P
    conv_id = "conv-truth-8"
    _clean_queue(conv_id)
    provider = MagicMock()
    provider.send_image_base64 = AsyncMock()

    with patch.object(P, "record_deferred_media_delivery") as m_rec:
        await P._dispatch_deferred_media(
            provider, "556799295671", {"id": conv_id}, {"id": "lead-1"},
        )

    provider.send_image_base64.assert_not_awaited()
    m_rec.assert_not_called()

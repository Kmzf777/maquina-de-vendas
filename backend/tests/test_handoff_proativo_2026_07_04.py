"""Testes do handoff proativo + instrumentação (auditoria 2026-07-04).

Cobre:
- Item 1: encaminhar_humano grava assigned_to (responsável) no update de desligamento.
- Item 2: carimbo estruturado metadata.handoff.
- Item 3: qualificar_lead persiste âncoras e só transfere com finalidade+volume.
- vendor_user_id_for_segment: resolve owner do pipeline e cai no fallback do João.
"""
import pytest
from unittest.mock import patch

from app.agent.tools import execute_tool


JOAO = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"


def _base_mocks(monkeypatch, stage="atacado", metadata=None):
    """Mocks comuns do fluxo de handoff. Retorna a lista que captura update_lead."""
    updates = []
    lead = {"id": "lead-1", "stage": stage, "phone": "+5511999999999", "metadata": metadata or {}}
    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: dict(lead))
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: updates.append(kw) or None)
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.move_deal_to_vendor_pipeline", lambda *a, **k: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.move_open_deal_for_handoff", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)
    monkeypatch.setattr("app.agent.tools.cancel_followups_by_phone", lambda *a, **k: None)
    return updates


@pytest.mark.asyncio
async def test_encaminhar_humano_grava_assigned_to_joao(monkeypatch):
    """Item 1: handoff de atacado resolve o vendedor e grava assigned_to no desligamento."""
    updates = _base_mocks(monkeypatch, stage="atacado")
    monkeypatch.setattr("app.agent.tools.vendor_user_id_for_segment", lambda seg: JOAO)

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João Brás", "motivo": "qualificado"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    disable = [u for u in updates if u.get("ai_enabled") is False]
    assert disable, "esperava um update desligando a IA"
    assert disable[0].get("assigned_to") == JOAO


@pytest.mark.asyncio
async def test_encaminhar_humano_sem_vendedor_nao_atribui(monkeypatch):
    """consumo/secretaria não têm vendedor: assigned_to fica ausente (self-service)."""
    updates = _base_mocks(monkeypatch, stage="consumo")
    monkeypatch.setattr("app.agent.tools.vendor_user_id_for_segment", lambda seg: None)

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João Brás", "motivo": "qualificado"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    disable = [u for u in updates if u.get("ai_enabled") is False]
    assert disable and "assigned_to" not in disable[0]


@pytest.mark.asyncio
async def test_encaminhar_humano_carimba_metadata_handoff(monkeypatch):
    """Item 2: o handoff grava um carimbo estruturado metadata.handoff."""
    updates = _base_mocks(monkeypatch, stage="atacado")
    monkeypatch.setattr("app.agent.tools.vendor_user_id_for_segment", lambda seg: JOAO)

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João Brás", "motivo": "qualificado"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    stamped = [u["metadata"]["handoff"] for u in updates if "metadata" in u and "handoff" in u["metadata"]]
    assert stamped, "esperava carimbo metadata.handoff"
    assert stamped[0]["vendedor_id"] == JOAO
    assert stamped[0]["segmento"] == "atacado"
    assert stamped[0]["motivo"] == "qualificado"


@pytest.mark.asyncio
async def test_qualificar_lead_persiste_ancoras_sem_handoff(monkeypatch):
    """Item 3: só finalidade → registra âncora e NÃO transfere."""
    updates = _base_mocks(monkeypatch, stage="atacado")

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "qualificar_lead",
            {"finalidade": "revenda em cafeteria"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    assert result == "Âncoras de qualificação registradas."
    # nenhum update desligou a IA (não houve handoff)
    assert not [u for u in updates if u.get("ai_enabled") is False]
    anchors = [u["metadata"]["qualificacao"] for u in updates if "metadata" in u and "qualificacao" in u["metadata"]]
    assert anchors and anchors[-1].get("finalidade") == "revenda em cafeteria"


@pytest.mark.asyncio
async def test_qualificar_lead_ancoras_completas_dispara_handoff(monkeypatch):
    """Item 3: finalidade + volume → handoff proativo (IA desligada + assigned_to)."""
    updates = _base_mocks(monkeypatch, stage="atacado")
    monkeypatch.setattr("app.agent.tools.vendor_user_id_for_segment", lambda seg: JOAO)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "qualificar_lead",
            {"finalidade": "revenda", "volume": "20 kg/mes"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    disable = [u for u in updates if u.get("ai_enabled") is False]
    assert disable, "âncoras completas deviam disparar o handoff (desligar a IA)"
    assert disable[0].get("assigned_to") == JOAO
    assert "encaminhado" in (result or "").lower()


def test_vendor_user_id_for_segment_le_o_cadastro_vendedores(monkeypatch):
    """b67f1c6b: a fonte de verdade é `vendedores.segmentos` (não mais o owner do pipeline
    nem o uuid do João escrito no código)."""
    from app.leads import service as svc
    from app.vendedores import service as vendedores

    vendedores.limpar_cache()
    monkeypatch.setattr(vendedores, "_carregar", lambda: [
        {"id": JOAO, "nome": "João Brás", "segmentos": ["atacado", "private_label"], "ativo": True},
        {"id": "u-arthur", "nome": "Arthur", "segmentos": ["exportacao"], "ativo": True},
    ])
    try:
        assert svc.vendor_user_id_for_segment("atacado") == JOAO
        assert svc.vendor_user_id_for_segment("private_label") == JOAO
        assert svc.vendor_user_id_for_segment("exportacao") == "u-arthur"
        assert svc.vendor_user_id_for_segment("consumo") is None
        assert svc.vendor_user_id_for_segment(None) is None
    finally:
        vendedores.limpar_cache()


def test_vendor_user_id_for_segment_sem_cadastro_nao_inventa(monkeypatch):
    """Cadastro vazio/indisponível → None (sem a antiga reserva JOAO_USER_ID)."""
    from app.leads import service as svc
    from app.vendedores import service as vendedores

    vendedores.limpar_cache()
    monkeypatch.setattr(vendedores, "_carregar", lambda: [])
    assert svc.vendor_user_id_for_segment("private_label") is None
    assert not hasattr(svc, "JOAO_USER_ID")

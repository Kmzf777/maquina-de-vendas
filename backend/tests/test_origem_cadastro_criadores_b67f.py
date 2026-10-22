"""Criadores de lead do backend gravam `leads.origem_cadastro` (cartão b67f1c6b, B8).

O default da coluna é 'inbound', e o gatilho de `entrada` dá ao lead inbound sem rastreio
uma entrada "Orgânico". Quem cria lead que NÃO chegou sozinho pelo WhatsApp tem de dizer
de onde veio, senão vira "lead de marketing" no dashboard.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _sb_captura(captured):
    def fake_insert(data):
        captured.append(data)
        res = MagicMock()
        res.data = [{**data, "id": "lead-novo"}]
        return MagicMock(execute=MagicMock(return_value=res))

    sel = MagicMock()
    sel.eq.return_value.execute.return_value = MagicMock(data=[])
    sel.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    tbl = MagicMock()
    tbl.select.return_value = sel
    tbl.insert.side_effect = fake_insert
    sb = MagicMock()
    sb.table.return_value = tbl
    return sb


def test_get_or_create_lead_inbound_nao_manda_origem():
    """Inbound real (webhook/buffer/LP): fica o default da coluna, 'inbound'."""
    cap = []
    with patch("app.leads.service.get_supabase", return_value=_sb_captura(cap)):
        from app.leads.service import get_or_create_lead
        get_or_create_lead("5511999999999", name="Maria")
    assert "origem_cadastro" not in cap[0]


def test_get_or_create_lead_grava_origem_informada():
    cap = []
    with patch("app.leads.service.get_supabase", return_value=_sb_captura(cap)):
        from app.leads.service import get_or_create_lead
        get_or_create_lead("5511999999999", origem_cadastro="manual")
    assert cap[0]["origem_cadastro"] == "manual"


def test_get_or_create_lead_bsuid_grava_origem_informada():
    cap = []
    with patch("app.leads.service.get_supabase", return_value=_sb_captura(cap)):
        from app.leads.service import get_or_create_lead
        get_or_create_lead("", bsuid="BR.ABC123", origem_cadastro="manual")
    assert cap[0]["origem_cadastro"] == "manual"


@pytest.mark.asyncio
async def test_disparo_cria_alvo_como_manual():
    from app.campaign.importer import ImportResult
    arquivo = AsyncMock()
    arquivo.read = AsyncMock(return_value=b"telefone\n5511987654321\n")
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 1
    with patch("app.broadcast.router._get_or_create_lead", return_value={"id": "L1"}) as gcl, \
         patch("app.broadcast.router._is_lead_blacklisted", return_value=False), \
         patch("app.broadcast.router._lead_has_active_relationship", return_value=False), \
         patch("app.broadcast.router.get_supabase", return_value=sb), \
         patch("app.broadcast.router.parse_csv",
               return_value=ImportResult(valid=["5511987654321"], invalid=[])):
        from app.broadcast.router import import_leads
        await import_leads(broadcast_id="bc", file=arquivo)
    gcl.assert_called_once_with("5511987654321", origem_cadastro="manual")


def test_lead_de_teste_da_automacao_e_manual_e_fase_valida():
    cap = []
    with patch("app.automation.test_runner.get_supabase", return_value=_sb_captura(cap)), \
         patch("app.automation.engine._get_env_tag", return_value="dev"):
        from app.automation.test_runner import _get_or_create_test_lead
        _get_or_create_test_lead("5511999999999")
    assert cap[0]["origem_cadastro"] == "manual"
    assert cap[0]["stage"] == "novo"  # 'Novo' não passa no CHECK de fase


@pytest.mark.asyncio
async def test_import_csv_de_campanha_e_csv_import():
    from app.campaign.importer import ImportResult
    arquivo = AsyncMock()
    arquivo.read = AsyncMock(return_value=b"x")
    cap = []
    with patch("app.campaign.router.get_supabase", return_value=_sb_captura(cap)), \
         patch("app.campaign.router.parse_csv",
               return_value=ImportResult(valid=["5511987654321"], invalid=[])):
        from app.campaign.router import import_leads
        await import_leads(campaign_id="c1", file=arquivo)
    assert cap[0]["origem_cadastro"] == "csv_import"

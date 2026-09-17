"""Disparo instantâneo da Valéria para leads do site institucional (cafecanastra.com).

O formulário de cafecanastra.com promete "Entraremos em contato em até 1 minuto!".
O delay padrão do webhook de LP (15min) quebraria essa promessa: as origens do site
resolvem para 0, enquanto as LPs de tráfego pago seguem com o delay configurado.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── _resolve_delay_minutes ───────────────────────────────────────────────────

def test_origem_do_site_em_portugues_dispara_sem_espera():
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("site-cafecanastra-atacado", 15) == 0


def test_origem_do_site_em_ingles_dispara_sem_espera():
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("site-cafecanastra-atacado-en", 15) == 0


def test_origem_do_site_em_espanhol_dispara_sem_espera():
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("site-cafecanastra-atacado-es", 15) == 0


def test_origem_de_landing_page_mantem_o_delay_configurado():
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("terceirizacao", 15) == 15


def test_origem_ausente_mantem_o_delay_configurado():
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("", 15) == 15


def test_origem_do_site_com_caixa_e_espaco_ainda_dispara_sem_espera():
    """`origem` chega do payload público — não confiar na forma exata."""
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("  Site-CafeCanastra-Atacado  ", 15) == 0


def test_origem_nova_do_site_nao_vira_instantanea_sozinha():
    """A regra é lista explícita, não prefixo: página nova nasce com o delay padrão."""
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("site-cafecanastra-varejo", 15) == 15


def test_delay_configurado_diferente_de_15_e_respeitado():
    """O override é só para o site; o resto espelha a config do CRM, seja ela qual for."""
    from app.lp_webhook.service import _resolve_delay_minutes
    assert _resolve_delay_minutes("atacado", 45) == 45


# ─── integração com process_landing_page_lead ────────────────────────────────

def _patches(config_delay: int = 15):
    """Colaboradores externos (Supabase/Redis) mockados; a lógica sob teste é real."""
    fake_lead = {"id": "lead-abc", "phone": "5511999990001", "name": "Maria", "email": None, "metadata": {}}
    fake_conv = {"id": "conv-xyz", "lead_id": "lead-abc", "channel_id": "ch-001"}
    fake_config = {
        "channel_id": "ch-001",
        "template_name": "lp_solicitacao_recebida",
        "language_code": "pt_BR",
        "delay_minutes": config_delay,
    }
    return (
        patch("app.lp_webhook.service.normalize_lp_phone", return_value=("5511999990001", "ok")),
        patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead),
        patch("app.lp_webhook.service.get_or_create_conversation", return_value=fake_conv),
        patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value=fake_config)),
        patch("app.lp_webhook.service._schedule_lp_welcome"),
        patch("app.lp_webhook.service.get_supabase"),
    )


async def _agendar_com_origem(origem: str, config_delay: int = 15):
    from app.lp_webhook.service import process_landing_page_lead

    p_phone, p_lead, p_conv, p_config, p_sched, p_sb = _patches(config_delay)
    payload = {
        "whatsapp": "5511999990001",
        "nome": "Maria Silva",
        "email": "maria@test.com",
        "origem": origem,
    }
    with p_phone, p_lead, p_conv, p_config, p_sched as mock_schedule, p_sb as mock_sb:
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        result = await process_landing_page_lead(payload, AsyncMock())
    assert result["ok"] is True
    mock_schedule.assert_called_once()
    return mock_schedule.call_args.kwargs["delay_minutes"]


@pytest.mark.anyio
async def test_lead_do_site_agenda_o_disparo_para_agora():
    assert await _agendar_com_origem("site-cafecanastra-atacado") == 0


@pytest.mark.anyio
async def test_lead_de_landing_page_continua_esperando_o_delay_configurado():
    assert await _agendar_com_origem("terceirizacao") == 15

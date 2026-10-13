"""Lead do botão de WhatsApp do anúncio Google (message asset): o texto pronto é a única pista."""
from unittest.mock import patch

import pytest

from app.leads.google_message_asset import (
    GOOGLE_ASSET_TRACKING,
    google_message_asset_tracking,
    stamp_google_message_asset,
)

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."


@pytest.mark.parametrize("text", [
    TEXTO,
    "ola, encontrei voces pelo google e gostaria de obter mais informacoes",
    "  OLÁ,   ENCONTREI VOCÊS PELO GOOGLE  ",
    TEXTO + " Quero revender café.",
])
def test_reconhece_texto_do_botao(text):
    assert google_message_asset_tracking(text) == {"utm_source": "google", "utm_medium": "cpc"}


@pytest.mark.parametrize("text", [None, "", "Olá", "Boa tarde", "achei no google maps", "vi no google"])
def test_nao_reconhece_outros_textos(text):
    assert google_message_asset_tracking(text) is None


def test_carimba_lead_sem_atribuicao():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1"}, TEXTO) is True
    upd.assert_called_once_with("L1", utm_source="google", utm_medium="cpc", traffic_type="paid")


@pytest.mark.parametrize("col", ["gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "utm_campaign"])
def test_nao_sobrescreve_atribuicao_existente(col):
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1", col: "x"}, TEXTO) is False
    upd.assert_not_called()


def test_texto_comum_nao_carimba():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1"}, "Bom dia") is False
    upd.assert_not_called()


def test_sem_lead_nao_carimba():
    with patch("app.leads.google_message_asset.update_lead") as upd:
        assert stamp_google_message_asset(None, TEXTO) is False
        assert stamp_google_message_asset({}, TEXTO) is False
    upd.assert_not_called()


def test_erro_do_banco_nao_propaga():
    with patch("app.leads.google_message_asset.update_lead", side_effect=RuntimeError("boom")):
        assert stamp_google_message_asset({"id": "L1"}, TEXTO) is False


def test_lead_carimbado_vira_google_ads_no_trafego():
    from app.campaigns.traffic_report import derive_channel
    assert derive_channel({**GOOGLE_ASSET_TRACKING, "traffic_type": "paid"}) == "Google Ads"

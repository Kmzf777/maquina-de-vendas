"""F5: toques que se perdiam (cartão B item 1) — botão do Google, retorno sem anúncio e tabela de
textos prontos (cartão C item 3)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import app.leads.google_message_asset as gma
from app.leads.google_message_asset import (
    RETORNO_DIAS, TEXTOS_PRONTOS, e_retorno, evento_retorno, evento_toque_texto_pronto,
    reconhecer_texto_pronto, registrar_retorno, stamp_google_message_asset,
)

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."
AGORA = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)  # 12h em Brasília


class _Banco:
    """lead_events em memória, com o índice único de dedupe_key, e conversations."""

    def __init__(self, conversas=None):
        self.eventos: list[dict] = []
        self.conversas = conversas or []

    def table(self, nome):
        return _Tab(self, nome)


class _Tab:
    def __init__(self, banco, nome):
        self.b, self.nome, self.f, self._ins = banco, nome, [], None

    def select(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def eq(self, c, v):
        self.f.append(lambda r: r.get(c) == v)
        return self

    def gte(self, c, v):
        self.f.append(lambda r: str(r.get(c) or "") >= v)
        return self

    def insert(self, row):
        self._ins = row
        return self

    def execute(self):
        if self._ins is not None:
            if any(e["dedupe_key"] == self._ins["dedupe_key"] for e in self.b.eventos):
                raise RuntimeError('duplicate key value violates unique constraint "lead_events_dedupe_key"')
            self.b.eventos.append(self._ins)
            return type("R", (), {"data": [self._ins]})()
        rows = self.b.eventos if self.nome == "lead_events" else self.b.conversas
        return type("R", (), {"data": [r for r in rows if all(f(r) for f in self.f)]})()


@pytest.fixture
def banco(monkeypatch):
    b = _Banco()
    monkeypatch.setattr(gma, "_sb", lambda: b)
    return b


# ── 1a. botão do Google ───────────────────────────────────────────────────────

def test_lead_com_ctwa_antigo_e_texto_do_google_grava_toque_e_nao_mexe_nas_colunas(banco):
    lead = {"id": "L1", "ctwa_clid": "C_ANTIGO", "meta_ad_id": "AD1"}
    with patch.object(gma, "update_lead") as upd:
        assert stamp_google_message_asset(lead, TEXTO) is False
    upd.assert_not_called()
    assert len(banco.eventos) == 1
    ev = banco.eventos[0]
    assert ev["event_type"] == "entrada" and ev["new_value"] == "Google Ads"
    assert ev["source"] == "google_message_asset"
    assert ev["metadata"]["campanha_nome"] == "WhatsApp do Google"
    assert not any(ev["metadata"].get(k) for k in ("gclid", "gbraid", "wbraid", "ctwa_clid", "fbclid"))
    # o toque é Google Ads no relatório
    from app.campaigns.traffic_report import canal_da_entrada
    assert canal_da_entrada({**ev, "occurred_at": AGORA.isoformat()}) == "Google Ads"


def test_segunda_mensagem_no_mesmo_dia_nao_duplica(banco):
    lead = {"id": "L1", "ctwa_clid": "C"}
    with patch.object(gma, "update_lead"):
        stamp_google_message_asset(lead, TEXTO)
        stamp_google_message_asset(lead, TEXTO + " Oi de novo")
    assert len(banco.eventos) == 1


def test_dedupe_e_por_dia_de_brasilia():
    linha = TEXTOS_PRONTOS[0]
    # 01h UTC de 07/11 ainda é 06/11 em Brasília
    a = evento_toque_texto_pronto("L1", linha, datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc))
    b = evento_toque_texto_pronto("L1", linha, datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc))
    c = evento_toque_texto_pronto("L1", linha, datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc))
    assert a["dedupe_key"] == b["dedupe_key"] == "entrada:google_message_asset:L1:2026-11-06"
    assert c["dedupe_key"] != a["dedupe_key"]


def test_lead_sem_origem_continua_carimbando_as_colunas_e_o_gatilho_grava(banco):
    with patch.object(gma, "update_lead") as upd:
        assert stamp_google_message_asset({"id": "L1"}, TEXTO) is True
    upd.assert_called_once()
    assert banco.eventos == []  # quem grava é o gatilho de leads (funde a entrada automática)


def test_toque_que_falha_no_banco_nao_propaga(monkeypatch):
    def _explode():
        raise RuntimeError("sem banco")
    monkeypatch.setattr(gma, "_sb", _explode)
    with patch.object(gma, "update_lead"):
        assert stamp_google_message_asset({"id": "L1", "gclid": "g"}, TEXTO) is False


# ── 1b. retorno sem anúncio ───────────────────────────────────────────────────

def _lead(dias_ultima=None, **kw):
    base = {"id": "L1", "created_at": (AGORA - timedelta(days=60)).isoformat()}
    if dias_ultima is not None:
        base["last_customer_message_at"] = (AGORA - timedelta(days=dias_ultima)).isoformat()
    return {**base, **kw}


def test_retorno_depois_de_7_dias_grava_toque(banco):
    assert registrar_retorno(_lead(7), "Oi, vocês têm café em grão?", tem_referral=False, agora=AGORA) is True
    ev = banco.eventos[0]
    assert ev["new_value"] == "WhatsApp direto" and ev["source"] == "retorno"
    assert ev["metadata"]["retorno"] is True and ev["metadata"]["dias_sem_conversa"] == 7


def test_6_dias_nao_e_retorno(banco):
    assert registrar_retorno(_lead(6), "Oi", tem_referral=False, agora=AGORA) is False
    assert banco.eventos == []


def test_com_referral_nao_e_direto(banco):
    # o toque do anúncio é gravado pelo gatilho (ctwa_clid/meta_ad_id), não como "direto"
    assert registrar_retorno(_lead(30), "Oi", tem_referral=True, agora=AGORA) is False
    assert banco.eventos == []


def test_texto_do_google_nao_e_retorno(banco):
    assert registrar_retorno(_lead(30), TEXTO, tem_referral=False, agora=AGORA) is False


def test_conversa_recente_de_saida_conta(banco):
    # disparo nosso há 2 dias: a resposta é conversa, não busca pela marca
    banco.conversas = [{"lead_id": "L1", "last_msg_at": (AGORA - timedelta(days=2)).isoformat()}]
    assert registrar_retorno(_lead(30), "Oi", tem_referral=False, agora=AGORA) is False


def test_lead_criado_agora_nao_e_retorno(banco):
    lead = {"id": "L1", "created_at": AGORA.isoformat()}
    assert registrar_retorno(lead, "Oi", tem_referral=False, agora=AGORA) is False


def test_lead_antigo_que_nunca_escreveu_e_retorno(banco):
    assert registrar_retorno(_lead(None), "Oi", tem_referral=False, agora=AGORA) is True


def test_retorno_no_mesmo_dia_nao_duplica(banco):
    registrar_retorno(_lead(10), "Oi", tem_referral=False, agora=AGORA)
    registrar_retorno(_lead(10), "Oi?", tem_referral=False, agora=AGORA + timedelta(minutes=5))
    assert len(banco.eventos) == 1


def test_regra_pura_do_retorno():
    assert RETORNO_DIAS == 7
    assert e_retorno(_lead(7), "oi", tem_referral=False, ultima_conversa=None, agora=AGORA)
    assert not e_retorno(_lead(6.9), "oi", tem_referral=False, ultima_conversa=None, agora=AGORA)
    assert evento_retorno("L1", AGORA, 9)["dedupe_key"] == "entrada:retorno:L1:2026-11-06"


# ── cartão C item 3: tabela de textos prontos ─────────────────────────────────

@pytest.mark.parametrize("texto", [TEXTO, "ola encontrei voces pelo GOOGLE", "  OLÁ,  ENCONTREI VOCÊS PELO GOOGLE "])
def test_reconhecedor_acha_o_texto_do_google(texto):
    linha = reconhecer_texto_pronto(texto)
    assert linha["canal"] == "Google Ads" and linha["campanha"] == "WhatsApp do Google"


@pytest.mark.parametrize("texto", [None, "", "vi no google", "Bom dia"])
def test_reconhecedor_ignora_o_resto(texto):
    assert reconhecer_texto_pronto(texto) is None


def test_reconhecedor_aceita_linha_nova(monkeypatch):
    nova = {"trecho": "vim pelo site do atacado", "canal": "Site atacado", "campanha": "wa.me atacado",
            "source": "site_atacado", "tracking": {"utm_source": "site", "utm_medium": "whatsapp",
                                                    "utm_campaign": "atacado"}}
    monkeypatch.setattr(gma, "TEXTOS_PRONTOS", gma.TEXTOS_PRONTOS + (nova,))
    assert reconhecer_texto_pronto("Olá, vim pelo site do Atacado")["source"] == "site_atacado"
    # texto de site não é o do Google: o carimbo de Google Ads não pega
    assert gma.google_message_asset_tracking("Olá, vim pelo site do atacado") is None


def test_trechos_estao_normalizados():
    for linha in TEXTOS_PRONTOS:
        assert linha["trecho"] == gma._normalize(linha["trecho"])


# ── webhook da Meta chama o retorno com o referral certo ──────────────────────

@pytest.mark.parametrize("kw, referral", [({}, False), ({"ctwa_clid": "C"}, True),
                                          ({"meta_ad_id": "A"}, True), ({"ctwa_origem": "x"}, True)])
def test_meta_register_lead_chama_retorno(kw, referral):
    from app.webhook import meta_router
    lead = {"id": "L1", "wa_id": "5511", "wa_id_confirmed_at": "x", "ctwa_clid": kw.get("ctwa_clid"),
            "meta_ad_id": kw.get("meta_ad_id"), "metadata": {"origem": "y"}}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset"), \
         patch("app.webhook.meta_router.registrar_retorno") as ret:
        meta_router._register_lead("5511", "Ana", kw.get("ctwa_clid"), kw.get("ctwa_origem"), None,
                                   kw.get("meta_ad_id"), text="Oi")
    ret.assert_called_once_with(lead, "Oi", tem_referral=referral)


def test_retorno_que_explode_nao_derruba_o_registro():
    from app.webhook import meta_router
    with patch("app.webhook.meta_router.get_or_create_lead", return_value={"id": "L1", "wa_id": "5511",
                                                                           "wa_id_confirmed_at": "x"}), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset"), \
         patch("app.webhook.meta_router.registrar_retorno", side_effect=RuntimeError("x")):
        meta_router._register_lead("5511", "Ana", text="Oi")

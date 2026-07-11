"""Nomes 'lixo conversacional' da LP não podem virar vocativo (forense 11/07).

Caso real: lead cadastrado como "Sim" pelo formulário da landing page — a Valéria
vocativou "olá Sim", "boa Sim" a conversa inteira. Respostas conversacionais
(sim/não/ok/teste...) não são nomes: sanitize_display_name deve derrubá-las para
None (fallback neutro "sem nome"), e o fluxo da LP deve passar por esse mesmo
funil em vez de aceitar qualquer token curto.
"""
import pytest


# ---------------------------------------------------------------------------
# sanitize_display_name — blocklist de respostas conversacionais
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [
    "Sim", "sim", "SIM", "não", "nao", "Ok", "okay", "blz",
    "teste", "Teste", "test", "testando",
    "quero", "quero sim", "sim quero",
    "obrigado", "obrigada", "valeu",
    "oi", "cliente", "lead", "whatsapp", "nome", "meu nome", "nao sei",
])
def test_sanitize_display_name_drops_conversational_junk(junk):
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name(junk) is None


@pytest.mark.parametrize("real", [
    "Anderson", "Simone", "Simão", "Simas", "Okada", "Testolini",
    "Sim Silva",  # nome composto raro passa: match é do nome INTEIRO normalizado
    "João Silva", "Valquíria",
])
def test_sanitize_display_name_keeps_real_names(real):
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name(real) == real


# ---------------------------------------------------------------------------
# LP: _sanitize_lead_name passa pelo mesmo funil
# ---------------------------------------------------------------------------

def test_lp_sanitize_drops_sim_and_preserves_raw_as_lp_message():
    from app.lp_webhook.service import _sanitize_lead_name
    clean, lp_message, email = _sanitize_lead_name("Sim")
    assert clean is None
    assert lp_message == "Sim"
    assert email is None


def test_lp_sanitize_keeps_real_name():
    from app.lp_webhook.service import _sanitize_lead_name
    clean, lp_message, email = _sanitize_lead_name("Anderson")
    assert clean == "Anderson"
    assert lp_message is None


def test_lp_sanitize_greeting_plus_name_still_recovers_name():
    from app.lp_webhook.service import _sanitize_lead_name
    clean, _, _ = _sanitize_lead_name("Boa tarde.... Luiz")
    assert clean == "Luiz"


def test_lp_sanitize_handle_is_dropped():
    from app.lp_webhook.service import _sanitize_lead_name
    clean, lp_message, _ = _sanitize_lead_name("Brunor_barista")
    assert clean is None
    assert lp_message == "Brunor_barista"

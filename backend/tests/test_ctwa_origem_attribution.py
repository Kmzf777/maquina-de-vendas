"""Opção B — atribuição do funil via CTWA: deriva `origem` do objeto `referral` do
anúncio Meta (source_url / headline / body) e carimba em leads.metadata.origem.

NOTA OPERACIONAL: depende do anúncio estar configurado como Click-to-WhatsApp para a
Meta entregar o `referral` no inbound. Hoje nenhum referral chega (0/10.808 logs) — este
parser fica dormente até o CTWA ser configurado no Ads Manager. O código é correto e
testado para o momento em que o dado passar a chegar.
"""
from unittest.mock import patch
import pytest

from app.webhook.meta_parser import parse_meta_webhook_payload, origem_from_referral


def _make_meta_payload(msg_dict: dict, from_number: str = "5511999999999") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "5500000000000", "phone_number_id": "999"},
                    "contacts": [{"profile": {"name": "Test"}}],
                    "messages": [{
                        "from": from_number, "id": "wamid.ctwa-org", "timestamp": "1716900000",
                        **msg_dict,
                    }],
                }
            }]
        }]
    }


# ── helper puro origem_from_referral ────────────────────────────────────────

@pytest.mark.parametrize("referral,expected", [
    ({"source_url": "https://atacado.cafecanastra.com/cafeatacado"}, "atacado"),
    ({"source_url": "https://atacado.cafecanastra.com/terceirizacaocafe"}, "terceirizacao"),
    ({"headline": "Café no atacado para sua loja"}, "atacado"),          # casa no headline
    ({"body": "Quero terceirização de café private label"}, "terceirizacao"),  # casa no body
    ({"source_url": "https://fb.me/abc", "headline": "Compre agora"}, None),    # sem sinal
    ({}, None),
    (None, None),
])
def test_origem_from_referral(referral, expected):
    assert origem_from_referral(referral) == expected


# ── parser popula ctwa_origem ───────────────────────────────────────────────

def test_parse_extracts_ctwa_origem_from_source_url():
    payload = _make_meta_payload({
        "type": "text", "text": {"body": "vi o anuncio"},
        "referral": {
            "source_type": "ad",
            "source_url": "https://atacado.cafecanastra.com/cafeatacado",
            "ctwa_clid": "clid_atac_1",
        },
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].ctwa_origem == "atacado"
    assert msgs[0].ctwa_clid == "clid_atac_1"  # não regrediu


def test_parse_organic_message_has_no_ctwa_origem():
    payload = _make_meta_payload({"type": "text", "text": {"body": "ola"}})
    msgs = parse_meta_webhook_payload(payload)
    assert msgs[0].ctwa_origem is None


# ── _register_lead carimba metadata.origem ──────────────────────────────────

# NOTA (merge wa_id_confirmed_at): _register_lead também carimba a procedência do wa_id —
# quando o lead ainda não tem wa_id_confirmed_at, dispara um update_lead(id,
# wa_id_confirmed_at=<timestamp>) além da lógica de origem. Estes testes validam o contrato de
# ORIGEM especificamente (via assert_any_call / ausência de kwarg metadata), tolerando a chamada
# extra de wa_id sem se acoplar ao timestamp não-determinístico dela.

def _has_origem_call(upd) -> bool:
    return any("metadata" in c.kwargs for c in upd.call_args_list)


def test_register_lead_stamps_origem_when_absent():
    """CTWA de atacado num lead sem origem → grava metadata.origem='atacado'.

    update_lead é chamado DUAS vezes: uma para o selo de wa_id, outra para a origem."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": None, "metadata": {}}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid=None, ctwa_origem="atacado")
    assert upd.call_count == 2
    upd.assert_any_call("L1", metadata={"origem": "atacado"})
    assert any("wa_id_confirmed_at" in c.kwargs for c in upd.call_args_list)


def test_register_lead_does_not_overwrite_existing_origem():
    """Origem já definida (first-touch vence) → não sobrescreve; nenhum update_lead carrega
    metadata (a chamada existente é só a de wa_id)."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": None,
                             "metadata": {"origem": "terceirizacao"}}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid=None, ctwa_origem="atacado")
    assert not _has_origem_call(upd)


def test_register_lead_no_origem_signal_is_noop():
    """Sem sinal de CTWA/origem → nenhum update_lead carrega ctwa_clid nem metadata
    (a chamada existente é só a de wa_id_confirmed_at)."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": None, "metadata": {}}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid=None, ctwa_origem=None)
    assert not any("ctwa_clid" in c.kwargs or "metadata" in c.kwargs for c in upd.call_args_list)

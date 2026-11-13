"""Lead de landing page passa a ser atendido pelos botões (13/11/2026).

Antes, `lp_webhook` fixava em toda conversa nova o perfil de IA `valeria_inbound`, e a
conversa vence o canal (`runner.fluxo_da_conversa`): o lead da LP nunca caía nos botões,
mesmo com o número da ValerIA já em `valeria_botoes_v1`. Agora:

  • a conversa da LP nasce SEM perfil e segue o do canal;
  • conversa que ainda carrega o pin antigo da LP (`valeria_inbound`) é solta;
  • a origem da LP diz o ramo (terceirização → P1, atacado → N1), e o primeiro
    contato abre direto nele, sem perguntar de novo "é pra qual caso?".
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.button_flow import valeria_entrada_lp as entrada_lp
from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner
from app.button_flow.engine import Texto


# ── Origem → nó de entrada ──────────────────────────────────────────────────

@pytest.mark.parametrize("origem,esperado", [
    ("terceirizacao", "P1"),
    ("  Terceirizacao ", "P1"),
    ("atacado", "N1"),
    ("site-cafecanastra-atacado", "N1"),
    ("site-cafecanastra-atacado-en", None),   # texto do fluxo é em português
    ("bling_webhook", None),
    ("", None),
    (None, None),
])
def test_entrada_da_origem(origem, esperado):
    assert entrada_lp.entrada_da_origem(origem) == esperado


def test_toda_entrada_e_no_do_registry_com_abertura():
    for no in set(entrada_lp.ENTRADA_POR_ORIGEM.values()):
        assert no in reg.NOS
        assert no in entrada_lp.ABERTURA_POR_ENTRADA
        assert entrada_lp.ABERTURA_POR_ENTRADA[no].startswith("oi! aqui é a Valéria")


# ── Primeiro contato abre no ramo da LP ────────────────────────────────────

def _estado_lp(no):
    return {"flow": reg.FLOW_ID, entrada_lp.CHAVE_ENTRADA: no}


@pytest.mark.parametrize("no", ["P1", "N1"])
def test_primeiro_contato_da_lp_abre_no_ramo(no):
    decisao = runner._decidir(None, Texto("oi"), _estado_lp(no), reg.NOS, reg.TERMINAIS, None)
    assert decisao.proximo_no == no
    assert decisao.mensagem.corpo == entrada_lp.ABERTURA_POR_ENTRADA[no]
    assert decisao.mensagem.botoes == reg.NOS[no].botoes
    assert not decisao.marcar_nudge


def test_entrada_desconhecida_cai_na_tela_de_entrada():
    decisao = runner._decidir(None, Texto("oi"), _estado_lp("ZZ"), reg.NOS, reg.TERMINAIS, None)
    assert decisao.proximo_no == reg.NO_ENTRADA


def test_sem_entrada_continua_na_tela_de_entrada():
    decisao = runner._decidir(None, Texto("oi"), None, reg.NOS, reg.TERMINAIS, None)
    assert decisao.proximo_no == reg.NO_ENTRADA


def test_pedido_de_saida_vence_a_entrada_da_lp():
    decisao = runner._decidir(None, Texto("pare"), _estado_lp("P1"), reg.NOS, reg.TERMINAIS, None)
    assert decisao.proximo_no == "T_OPTOUT"


def test_entrada_some_do_estado_depois_do_primeiro_turno():
    campos = runner.proximo_estado(_estado_lp("P1"), "P1")
    assert entrada_lp.CHAVE_ENTRADA not in campos
    assert campos["node"] == "P1"
    assert campos["ramo"] == "private_label"


# ── lp_webhook: conversa sem pin e com a entrada gravada ───────────────────

def _rodar_lp(conv, origem, perfil_inbound="prof-inbound"):
    from app.lp_webhook.service import process_landing_page_lead

    fake_lead = {"id": "lead-1", "phone": "5534999990001", "name": "Ana", "email": None,
                 "metadata": {}}
    payload = {"whatsapp": "5534999990001", "nome": "Ana", "email": "", "origem": origem}
    config = {"channel_id": "ch-1", "template_name": "lp_tpl", "language_code": "pt_BR",
              "delay_minutes": 15}
    with patch("app.lp_webhook.service.normalize_phone", return_value="5534999990001"), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_or_create_conversation",
               return_value=conv) as goc, \
         patch("app.lp_webhook.service.get_profile_id_by_prompt_key",
               return_value=perfil_inbound), \
         patch("app.lp_webhook.service.update_conversation") as upd, \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value=config)), \
         patch("app.lp_webhook.service._schedule_lp_welcome"), \
         patch("app.lp_webhook.service.get_supabase", return_value=MagicMock()):
        import asyncio
        result = asyncio.run(process_landing_page_lead(payload, AsyncMock()))
    return result, goc, upd


def test_lp_cria_conversa_sem_fixar_perfil():
    _, goc, _ = _rodar_lp({"id": "c1", "agent_profile_id": None, "flow_state": None}, "atacado")
    args, kwargs = goc.call_args
    assert kwargs.get("agent_profile_id") is None
    assert len(args) <= 2


def test_lp_grava_a_entrada_do_ramo_na_conversa_nova():
    result, _, upd = _rodar_lp({"id": "c1", "agent_profile_id": None, "flow_state": None},
                               "terceirizacao")
    assert result["ok"] is True
    upd.assert_called_once()
    conv_id, = upd.call_args.args
    assert conv_id == "c1"
    assert upd.call_args.kwargs == {
        "flow_state": {"flow": reg.FLOW_ID, entrada_lp.CHAVE_ENTRADA: "P1"},
    }


def test_lp_solta_o_pin_antigo_de_ia():
    _, _, upd = _rodar_lp({"id": "c1", "agent_profile_id": "prof-inbound", "flow_state": None},
                          "origem-sem-ramo")
    upd.assert_called_once()
    assert upd.call_args.kwargs == {"agent_profile_id": None}


def test_lp_nao_mexe_em_perfil_de_outro_dono():
    # Perfil fixado por outro disparo (broadcast, outbound) não é o pin da LP.
    _, _, upd = _rodar_lp({"id": "c1", "agent_profile_id": "prof-outbound", "flow_state": None},
                          "origem-sem-ramo")
    upd.assert_not_called()


def test_lp_nao_reinicia_conversa_que_ja_esta_no_fluxo():
    conv = {"id": "c1", "agent_profile_id": None,
            "flow_state": {"flow": reg.FLOW_ID, "node": "N3", "nudges": 0}}
    _, _, upd = _rodar_lp(conv, "atacado")
    upd.assert_not_called()


def test_preparar_conversa_nao_levanta_se_o_banco_falhar():
    from app.lp_webhook import service

    conv = {"id": "c1", "agent_profile_id": None, "flow_state": None}
    with patch.object(service, "update_conversation", side_effect=RuntimeError("db")), \
         patch.object(service, "get_profile_id_by_prompt_key", return_value=None):
        service._preparar_conversa_para_botoes(conv, "atacado")  # não levanta

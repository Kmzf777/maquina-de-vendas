"""Opt-out determinístico: o botão "Nao tenho interesse" tem de virar blacklist.

A spec (§7) afirma que o terceiro QUICK_REPLY dos templates "já alimenta a blacklist".
Era FALSO para o público das esteiras: `leads.opt_out` só é gravado pela tool
`registrar_optout`, que SÓ o agente LLM chama — e lead de esteira tem `ai_enabled=False`
por definição (o handoff desliga a IA), num número de vendedor que roda `mode='human'`.
Nos dois casos o inbound retorna ANTES do agente. Apertar o botão cancelava um enrollment
e mais nada: sem `opt_out`, sem pipeline Blacklist, sem cancelar follow-up. Como as
esteiras reinscrevem o lead depois, quem disse "não tenho interesse" voltava a receber.

Duas invariantes que este arquivo trava:

1. IGUALDADE normalizada, nunca substring — "não tenho interesse em cápsulas, só em
   grãos" é interesse, não opt-out. Um `in` ingênuo mandaria um lead quente para a
   blacklist permanente.
2. A gravação usa os MESMOS campos da tool (`opt_out=True` + `apply_optout_side_effects`),
   para não existirem duas definições de "está na blacklist".
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.campaigns.worker import handle_optout_reply, is_optout_reply


# ── 1. Casamento de texto ────────────────────────────────────────────────────────


class TestCasamentoPorIgualdade:
    @pytest.mark.parametrize("texto", [
        "Nao tenho interesse",
        "Não tenho interesse",
        "NÃO TENHO INTERESSE",
        "  não tenho interesse  ",
        "Não tenho interesse.",
        "não tenho interesse!",
        "Parar mensagens",
        "parar mensagens.",
    ])
    def test_rotulo_do_botao_e_optout(self, texto):
        assert is_optout_reply(texto) is True

    @pytest.mark.parametrize("texto", [
        # O caso que um `in` ingênuo destruiria: lead QUENTE.
        "não tenho interesse em cápsulas, só em grãos",
        "nao tenho interesse nesse, tem outro?",
        "por enquanto não tenho interesse mas me manda o catálogo",
        "tenho interesse",
        "quero parar mensagens de outro fornecedor, mas o de vocês pode continuar",
        "interesse",
        "",
        None,
    ])
    def test_texto_que_nao_e_o_botao_nao_e_optout(self, texto):
        assert is_optout_reply(texto) is False


# ── 2. Gravação ──────────────────────────────────────────────────────────────────


LEAD = {"id": "lead-1", "phone": "5511999999999", "ai_enabled": False}


class TestGravacao:
    def test_grava_os_mesmos_campos_da_tool(self):
        with (
            patch("app.leads.service.update_lead") as mock_update,
            patch("app.leads.service.apply_optout_side_effects") as mock_side,
            patch("app.leads.service.append_lead_observation"),
            patch("app.leads.service.save_message"),
        ):
            assert handle_optout_reply(LEAD, "Nao tenho interesse", conversation_id="conv-1") is True
        mock_update.assert_called_once_with("lead-1", ai_enabled=False, opt_out=True)
        assert mock_side.call_args.args[0] == "lead-1"
        assert mock_side.call_args.args[1] == "5511999999999"

    def test_texto_fora_do_rotulo_nao_grava_nada(self):
        with (
            patch("app.leads.service.update_lead") as mock_update,
            patch("app.leads.service.apply_optout_side_effects") as mock_side,
        ):
            assert handle_optout_reply(LEAD, "não tenho interesse em cápsulas, só em grãos") is False
        mock_update.assert_not_called()
        mock_side.assert_not_called()

    def test_lead_ja_em_optout_e_no_op(self):
        with patch("app.leads.service.update_lead") as mock_update:
            assert handle_optout_reply({**LEAD, "opt_out": True}, "Nao tenho interesse") is False
        mock_update.assert_not_called()

    def test_erro_ao_gravar_nao_levanta(self):
        """Fail-soft: opt-out que falha não pode derrubar o processamento da mensagem."""
        with patch("app.leads.service.update_lead", side_effect=RuntimeError("boom")):
            assert handle_optout_reply(LEAD, "Nao tenho interesse") is False

    def test_erro_nos_efeitos_colaterais_nao_levanta(self):
        with (
            patch("app.leads.service.update_lead"),
            patch("app.leads.service.apply_optout_side_effects", side_effect=RuntimeError("boom")),
            patch("app.leads.service.append_lead_observation"),
            patch("app.leads.service.save_message"),
        ):
            assert handle_optout_reply(LEAD, "Nao tenho interesse") is True

    def test_nao_envia_mensagem_nenhuma_para_quem_pediu_para_sair(self):
        with (
            patch("app.leads.service.update_lead"),
            patch("app.leads.service.apply_optout_side_effects"),
            patch("app.leads.service.append_lead_observation"),
            patch("app.leads.service.save_message") as mock_save,
        ):
            handle_optout_reply(LEAD, "Nao tenho interesse", conversation_id="conv-1")
        # save_message aqui é registro interno (role=system), nunca envio ao cliente.
        assert mock_save.call_args.args[1] == "system"


# ── 3. O inbound de verdade ──────────────────────────────────────────────────────


def _lead(ai_enabled=False):
    return {"id": "lead-1", "phone": "+5511999999999", "stage": "atacado",
            "status": "active", "ai_enabled": ai_enabled, "name": "Teste"}


def _channel(mode="human"):
    return {"id": "ch-1", "is_active": True, "mode": mode,
            "agent_profiles": {"id": "p1", "stages": {}}, "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}}


def _conversation():
    return {"id": "conv-1", "lead_id": "lead-1", "channel_id": "ch-1",
            "stage": "atacado", "status": "active", "followup_enabled": True}


async def _inbound(texto, *, ai_enabled=False, mode="human"):
    """Roda o processador de verdade e devolve o mock de handle_optout_reply."""
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .single.return_value.execute.return_value.data) = {"unread_count": 0}
    with (
        patch("app.buffer.processor.get_or_create_lead", return_value=_lead(ai_enabled)),
        patch("app.buffer.processor.get_channel_by_id", return_value=_channel(mode)),
        patch("app.buffer.processor.get_provider", return_value=AsyncMock()),
        patch("app.buffer.processor.get_or_create_conversation", return_value=_conversation()),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message"),
        patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="")),
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor.update_conversation"),
        patch("app.buffer.processor._schedule_followup"),
        patch("app.buffer.processor.get_supabase", return_value=sb),
        patch("app.buffer.processor._update_last_msg"),
        patch("app.buffer.processor.advance_deal_on_reply"),
        patch("app.buffer.processor._maybe_send_handoff_bridge", new=AsyncMock()),
        patch("app.campaigns.worker.handle_campaign_reply"),
        patch("app.campaigns.worker.handle_optout_reply") as mock_optout,
    ):
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", texto, "ch-1")
    return mock_optout


@pytest.mark.asyncio
async def test_optout_roda_antes_do_return_de_canal_humano():
    """Canal do vendedor é `mode='human'` — o gate mais precoce. Se o opt-out fosse
    gravado dentro do ramo de `ai_enabled=False`, este caminho nunca gravaria nada."""
    mock_optout = await _inbound("Nao tenho interesse", ai_enabled=False, mode="human")
    mock_optout.assert_called_once()
    assert mock_optout.call_args.args[0]["id"] == "lead-1"
    assert mock_optout.call_args.args[1] == "Nao tenho interesse"


@pytest.mark.asyncio
async def test_optout_roda_com_ai_enabled_false_em_canal_de_ia():
    mock_optout = await _inbound("Nao tenho interesse", ai_enabled=False, mode="ai")
    mock_optout.assert_called_once()


@pytest.mark.asyncio
async def test_inbound_real_grava_opt_out_de_ponta_a_ponta():
    """Sem mock do handler: o botão tem de chegar em `leads.opt_out=True` de verdade."""
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value
       .single.return_value.execute.return_value.data) = {"unread_count": 0}
    with (
        patch("app.buffer.processor.get_or_create_lead", return_value=_lead(False)),
        patch("app.buffer.processor.get_channel_by_id", return_value=_channel("human")),
        patch("app.buffer.processor.get_provider", return_value=AsyncMock()),
        patch("app.buffer.processor.get_or_create_conversation", return_value=_conversation()),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message"),
        patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="")),
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor.update_conversation"),
        patch("app.buffer.processor._schedule_followup"),
        patch("app.buffer.processor.get_supabase", return_value=sb),
        patch("app.buffer.processor._update_last_msg"),
        patch("app.buffer.processor.advance_deal_on_reply"),
        patch("app.buffer.processor._maybe_send_handoff_bridge", new=AsyncMock()),
        patch("app.campaigns.worker.handle_campaign_reply"),
        patch("app.leads.service.update_lead") as mock_update,
        patch("app.leads.service.apply_optout_side_effects") as mock_side,
        patch("app.leads.service.append_lead_observation"),
        patch("app.leads.service.save_message"),
    ):
        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "Nao tenho interesse", "ch-1")
    assert any(
        c.args == ("lead-1",) and c.kwargs == {"ai_enabled": False, "opt_out": True}
        for c in mock_update.call_args_list
    ), mock_update.call_args_list
    mock_side.assert_called_once()


@pytest.mark.asyncio
async def test_lead_sob_a_ia_continua_arbitrado_pelo_LLM():
    """Público da IA não muda: negativa reflexa no início do contato tem a escada do
    prompt (Anchor-Disrupt-Ask) e o guardrail anti-falso-positivo de 22/06. Blacklistar
    aqui seria a regressão que aquela auditoria existe para impedir."""
    mock_optout = await _inbound("Nao tenho interesse", ai_enabled=True, mode="ai")
    mock_optout.assert_not_called()


# ── 4. Camada 2: guardrail no instante do envio ──────────────────────────────────


@pytest.mark.asyncio
async def test_send_node_nao_dispara_para_lead_na_blacklist():
    """Marcar a blacklist só vale se alguém olhar para ela no momento do envio.

    O motor de campanhas não tinha o guardrail que `broadcast/worker.py` tem desde
    25/06. A camada 1 (filtro no gatilho) não cobre o enrollment JÁ criado: opt-out
    registrado no meio de uma esteira — pelo botão, pela tool ou pelo botão manual do
    operador, que não cancelam enrollment nenhum — deixava o próximo toque sair.
    """
    from app.campaigns.worker import _execute_send_node

    provider = AsyncMock()
    lead = {"id": "lead-1", "phone": "5511999999999"}
    node = {"config": {"template_name": "esteira_reposicao_v1", "channel_id": "ch-1"}}
    with (
        patch("app.leads.service.is_lead_blacklisted", return_value=True) as mock_bl,
        patch("app.whatsapp.registry.get_provider", return_value=provider),
        patch("app.channels.service.get_channel_by_id", return_value=_channel()),
    ):
        wamid = await _execute_send_node(
            {"id": "e1", "lead_id": "lead-1"}, node, lead, __import__("datetime").datetime.now(),
        )
    assert wamid is None
    mock_bl.assert_called_once_with("lead-1")
    provider.send_template.assert_not_called()

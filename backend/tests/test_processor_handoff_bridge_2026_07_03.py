"""TDD da ponte pos-handoff no canal da Valeria (Frente B1, 2026-07-03).

Casos reais que motivam esta ponte (auditoria 01-02/07): Maycon mandou um audio
reclamando depois do handoff e ninguem respondeu; Juliana escreveu 4x seguidas no
mesmo numero da Valeria, culminando em "Tem algum problema voces responderem?".
Em ambos, o lead ja tinha sido passado pro Joao (encaminhar_humano seta
human_control=True, ai_enabled=False), mas o gate `if not lead.get("ai_enabled",
True)` em process_buffered_messages so logava e retornava — silencio puro.

A ponte e uma sinalizacao ESTATICA de roteamento (sem LLM — o handoff encerra a
conversa automatica por contrato) com cooldown Redis fail-CLOSED: na duvida (Redis
fora, condicao ambigua), fica em silencio — spam e pior que vacuo, e o watchdog
Check 2 cobre os orfaos de verdade (ex.: Rafael, sem human_control).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import SUPERVISOR_NAME, SUPERVISOR_PHONE
from app.buffer import processor as P
from tests.test_buffer_recovery_hardening_2026_07_02 import FakeRedis as _BaseFakeRedis


class _BridgeFakeRedis(_BaseFakeRedis):
    """Estende o FakeRedis do watchdog (A1) com semantica NX real.

    A base (test_buffer_recovery_hardening_2026_07_02.FakeRedis) sempre sobrescreve
    o valor incondicionalmente — suficiente pra buffer/recovery, mas o cooldown da
    ponte depende de `SET ... NX` recusar quando a chave ja existe (senao nao da pra
    testar o caso "segunda mensagem dentro da janela de cooldown"). Estende em vez
    de duplicar a classe inteira.
    """

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._strings:
            return None  # chave ja existe -> SETNX nao seta (fail-closed no chamador)
        self._strings[key] = value
        return True


def _make_lead(**overrides) -> dict:
    lead = {
        "id": "lead-juliana",
        "phone": "+5511999990001",
        "stage": "atacado",
        "status": "converted",
        "human_control": True,
        "ai_enabled": False,
        "opt_out": False,
        "name": "Juliana",
    }
    lead.update(overrides)
    return lead


def _make_channel(**overrides) -> dict:
    channel = {
        "id": "ch-1",
        "is_active": True,
        "mode": "ai",
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    channel.update(overrides)
    return channel


def _make_conversation(**overrides) -> dict:
    conversation = {
        "id": "conv-juliana",
        "lead_id": "lead-juliana",
        "channel_id": "ch-1",
        "stage": "atacado",
        "status": "active",
        "followup_enabled": True,
    }
    conversation.update(overrides)
    return conversation


def _make_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.bridge1"}]})
    provider.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.card1"}]})
    return provider


def _sb_mock() -> MagicMock:
    """Supabase mock minimo p/ os blocos pre-gate (unread_count, last_customer_message_at)."""
    return MagicMock(table=MagicMock(return_value=MagicMock(
        update=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(execute=MagicMock())))),
        select=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            single=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))))
        )))),
    )))


# --- Unit tests: constantes ---------------------------------------------------


@pytest.mark.asyncio
async def test_bridge_texto_exato_voz_da_valeria():
    """Trava de regressao: o texto da ponte e EXATAMENTE o do brief (voz da Valeria)."""
    assert P._BRIDGE_TEXT == (
        "seu atendimento tá com o João agora\n\n"
        "se preferir, chama ele direto no contato que te mandei aqui em cima que ele te responde por lá"
    )


@pytest.mark.asyncio
async def test_bridge_cooldowns_batem_com_o_brief():
    assert P._BRIDGE_COOLDOWN_SECONDS == 4 * 3600
    assert P._BRIDGE_CARD_COOLDOWN_SECONDS == 24 * 3600


# --- Unit tests: _maybe_send_handoff_bridge -----------------------------------


@pytest.mark.asyncio
async def test_bridge_caso_juliana_envia_texto_e_cartao():
    """Caso Juliana: handoff completo (human_control=True, opt_out=False, stage!=perdido)
    -> ponte enviada 1x, salva com sent_by="bridge", cartao enviado (1a vez) + system message."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is True
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_TEXT)
    provider.send_contact.assert_awaited_once_with(
        lead["phone"], contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE,
    )

    assert mock_save.call_count == 2
    bridge_call = mock_save.call_args_list[0]
    assert bridge_call.args[:5] == (
        conversation["id"], lead["id"], "assistant", P._BRIDGE_TEXT, conversation["stage"],
    )
    assert bridge_call.kwargs["sent_by"] == "bridge"
    assert bridge_call.kwargs["wamid"] == "wamid.bridge1"

    card_call = mock_save.call_args_list[1]
    assert card_call.args[:5] == (
        conversation["id"], lead["id"], "system",
        "[ponte] cartão de contato de João - Café Canastra reenviado",
        conversation["stage"],
    )
    assert card_call.kwargs["sent_by"] == "bridge"

    # As duas chaves de cooldown ficaram gravadas (1 ponte + 1 cartao no periodo).
    assert fake_redis._strings[f"bridge:{conversation['id']}"] == "1"
    assert fake_redis._strings[f"bridge_card:{conversation['id']}"] == "1"


@pytest.mark.asyncio
async def test_bridge_cooldown_ativo_segunda_mensagem_nao_reenvia():
    """Segunda mensagem 5 min depois (chave de cooldown existente no FakeRedis) -> NADA
    enviado."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()
    fake_redis._strings[f"bridge:{conversation['id']}"] = "1"  # ponte ja disparada ha 5 min

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is False
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_stage_perdido_nao_envia():
    """Lead descartado (registrar_sem_interesse_atual: stage='perdido') -> ponte NAO
    dispara. As condicoes devem falhar ANTES de tocar o Redis."""
    lead = _make_lead(stage="perdido")
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    mock_redis = AsyncMock()

    with patch("app.buffer.processor._get_buffer_redis", return_value=mock_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is False
    mock_redis.set.assert_not_called()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_opt_out_nao_envia():
    """Lead em opt-out (registrar_optout: opt_out=True) -> ponte NAO dispara."""
    lead = _make_lead(opt_out=True)
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    mock_redis = AsyncMock()

    with patch("app.buffer.processor._get_buffer_redis", return_value=mock_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is False
    mock_redis.set.assert_not_called()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_sem_human_control_orfao_nao_envia():
    """Orfao sem handoff formal (human_control=False, ex.: caso Rafael) -> ponte NAO
    dispara; o Check 2 do watchdog e quem cobre esse estado (nao e um handoff real)."""
    lead = _make_lead(human_control=False)
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    mock_redis = AsyncMock()

    with patch("app.buffer.processor._get_buffer_redis", return_value=mock_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is False
    mock_redis.set.assert_not_called()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_redis_indisponivel_fail_closed_sem_excecao():
    """Redis lancando no SET de cooldown -> fail-CLOSED: nada enviado, sem propagar
    excecao (na duvida, silencio: spam e pior que vacuo)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    boom_redis = AsyncMock()
    boom_redis.set = AsyncMock(side_effect=RuntimeError("redis indisponivel"))

    with patch("app.buffer.processor._get_buffer_redis", return_value=boom_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )  # nao deve levantar

    assert sent is False
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_rehearsal_mode_nao_envia(monkeypatch):
    """REHEARSAL_MODE=true (execucao de teste/automacao) -> ponte NAO dispara."""
    monkeypatch.setenv("REHEARSAL_MODE", "true")
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    mock_redis = AsyncMock()

    with patch("app.buffer.processor._get_buffer_redis", return_value=mock_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is False
    mock_redis.set.assert_not_called()
    provider.send_text.assert_not_awaited()
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_bridge_cartao_em_cooldown_so_texto_sem_cartao():
    """Cartao: com bridge_card: ja setado e bridge: livre -> so texto, sem cartao (nao
    duplica o cartao do Joao dentro da janela de 24h, mesmo reenviando o texto)."""
    lead = _make_lead()
    conversation = _make_conversation()
    channel = _make_channel()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()
    fake_redis._strings[f"bridge_card:{conversation['id']}"] = "1"

    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis), \
         patch("app.buffer.processor.save_message") as mock_save:
        sent = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversation, channel, provider,
        )

    assert sent is True
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_TEXT)
    provider.send_contact.assert_not_awaited()
    assert mock_save.call_count == 1
    assert mock_save.call_args.kwargs["sent_by"] == "bridge"


# --- Integration tests: wiring dentro do gate ai_enabled ----------------------


@pytest.mark.asyncio
async def test_processor_gate_aciona_ponte_e_nao_roda_ia_caso_juliana():
    """Caso Juliana (4 mensagens apos o handoff, culminando em "Tem algum problema
    voces responderem?"): o gate ai_enabled aciona a ponte e a IA NUNCA roda
    (run_agent nao e chamado); _update_last_msg + return seguem como hoje."""
    lead = _make_lead()
    channel = _make_channel()
    conversation = _make_conversation()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()

    P_ = "app.buffer.processor."
    with patch(P_ + "get_or_create_lead", return_value=lead), \
         patch(P_ + "get_channel_by_id", return_value=channel), \
         patch(P_ + "get_provider", return_value=provider), \
         patch(P_ + "get_or_create_conversation", return_value=conversation), \
         patch(P_ + "get_active_enrollment", return_value=None), \
         patch(P_ + "save_message") as mock_save, \
         patch(P_ + "run_agent") as mock_agent, \
         patch(P_ + "_is_recent_duplicate", return_value=False), \
         patch(P_ + "get_supabase", return_value=_sb_mock()), \
         patch(P_ + "_get_buffer_redis", return_value=fake_redis), \
         patch(P_ + "_update_last_msg") as mock_update_last:

        await P.process_buffered_messages(
            lead["phone"], "Tem algum problema vocês responderem?", channel["id"],
        )

    mock_agent.assert_not_called()
    provider.send_text.assert_awaited_once_with(lead["phone"], P._BRIDGE_TEXT)
    provider.send_contact.assert_awaited_once()
    # user message + bridge text + system card = 3 save_message calls
    assert mock_save.call_count == 3
    assert mock_save.call_args_list[0].args[2] == "user"
    assert mock_save.call_args_list[1].kwargs.get("sent_by") == "bridge"
    mock_update_last.assert_called_once_with(conversation["id"])


@pytest.mark.asyncio
async def test_processor_gate_segunda_mensagem_no_cooldown_fluxo_retorna_normal():
    """Segunda mensagem do lead ~5 min depois (mesmo cooldown Redis) -> gate NAO
    reenvia a ponte, mas o processor segue retornando normalmente (sem excecao)."""
    lead = _make_lead()
    channel = _make_channel()
    conversation = _make_conversation()
    provider = _make_provider()
    fake_redis = _BridgeFakeRedis()  # compartilhado entre as 2 chamadas -> cooldown persiste

    P_ = "app.buffer.processor."
    with patch(P_ + "get_or_create_lead", return_value=lead), \
         patch(P_ + "get_channel_by_id", return_value=channel), \
         patch(P_ + "get_provider", return_value=provider), \
         patch(P_ + "get_or_create_conversation", return_value=conversation), \
         patch(P_ + "get_active_enrollment", return_value=None), \
         patch(P_ + "save_message") as mock_save, \
         patch(P_ + "run_agent") as mock_agent, \
         patch(P_ + "_is_recent_duplicate", return_value=False), \
         patch(P_ + "get_supabase", return_value=_sb_mock()), \
         patch(P_ + "_get_buffer_redis", return_value=fake_redis), \
         patch(P_ + "_update_last_msg") as mock_update_last:

        await P.process_buffered_messages(lead["phone"], "cade a resposta?", channel["id"])
        provider.send_text.reset_mock()
        provider.send_contact.reset_mock()
        mock_save.reset_mock()

        # 2a mensagem, ~5 min depois -- mesma chave de cooldown ainda ativa no fake redis.
        await P.process_buffered_messages(lead["phone"], "alo?", channel["id"])

    mock_agent.assert_not_called()
    provider.send_text.assert_not_awaited()
    provider.send_contact.assert_not_awaited()
    # so a mensagem do usuario e salva; nenhuma bolha da ponte na 2a rodada
    assert mock_save.call_count == 1
    assert mock_save.call_args_list[0].args[2] == "user"
    assert mock_update_last.call_count == 2

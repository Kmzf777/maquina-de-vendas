"""Gate INBOUND do bloqueio de lead (18/09/2026).

`process_buffered_messages` é o único estreitamento por onde passam TODOS os caminhos
inbound (meta_router, webhook/router legado, buffer/flusher e buffer/recovery). O gate
mora lá, logo após `get_or_create_lead`, e descarta o turno quando `leads.opt_out` é
verdadeiro.

O que estes testes provam:
- lead bloqueado → nada é persistido: `get_or_create_conversation` e `save_message` não
  são chamados e a função retorna cedo (a mensagem é descartada em definitivo);
- o gate está ANTES do trabalho caro e dos efeitos colaterais — `_resolve_media`
  (download/transcrição) e `advance_deal_on_reply` (que moveria o card de volta para
  'Respondeu' e desfaria a ida para a Blacklist) não chegam a rodar;
- lead sem `opt_out` → o fluxo segue normalmente (regressão do caminho feliz).

Regra de patch do repo: `get_or_create_lead`, `get_or_create_conversation` e
`save_message` são importados no TOPO de `app/buffer/processor.py`, então patchamos
`app.buffer.processor.<nome>` (módulo consumidor).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_channel():
    return {
        "id": "chan-uuid",
        "name": "Test",
        "mode": "ai",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "12345", "access_token": "tok"},
        "agent_profiles": {
            "id": "profile-uuid", "model": "gemini-2.0-flash",
            "base_prompt": "You are ValerIA", "stages": {},
        },
    }


def _lead(opt_out):
    """Lead como `get_or_create_lead` devolve: select("*"), logo `opt_out` vem junto."""
    return {
        "id": "lead-1",
        "phone": "5511999999999",
        "ai_enabled": True,
        "stage": "consumo",
        "opt_out": opt_out,
    }


@pytest.mark.asyncio
async def test_lead_bloqueado_nao_persiste_nada():
    """opt_out=True → sem conversa, sem mensagem, sem agente. Retorno antecipado."""
    from app.buffer.processor import process_buffered_messages

    with patch("app.buffer.processor.get_or_create_lead", return_value=_lead(True)), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()) as mock_channel, \
         patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor.get_or_create_conversation") as mock_conv, \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor.get_supabase"):
        await process_buffered_messages(
            "5511999999999", "oi", "chan-uuid", wamid="wamid_bloqueado_1"
        )

    mock_conv.assert_not_called()
    mock_save.assert_not_called()
    mock_agent.assert_not_called()
    # O gate fica ANTES do lookup de canal — prova a posição, não só o efeito.
    mock_channel.assert_not_called()


@pytest.mark.asyncio
async def test_lead_bloqueado_nao_paga_midia_nem_mexe_no_card():
    """O gate precede o trabalho caro e os efeitos que desfariam o próprio bloqueio.

    `_resolve_media` (download/transcrição de áudio) é o item mais caro do turno, e
    `advance_deal_on_reply` moveria o card de volta para 'Respondeu', tirando o lead da
    Blacklist. Um gate posicionado depois deles anularia o bloqueio.
    """
    from app.buffer.processor import process_buffered_messages

    with patch("app.buffer.processor.get_or_create_lead", return_value=_lead(True)), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor._resolve_media") as mock_media, \
         patch("app.buffer.processor.advance_deal_on_reply") as mock_advance, \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor.get_supabase"):
        await process_buffered_messages(
            "5511999999999", "[audio:https://exemplo/audio.ogg]", "chan-uuid",
            wamid="wamid_bloqueado_2",
        )

    mock_media.assert_not_called()
    mock_advance.assert_not_called()
    mock_save.assert_not_called()
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_lead_bloqueado_por_opt_out_ausente_ou_falso_nao_barra():
    """`opt_out` ausente (lead legado) ou False não pode barrar ninguém."""
    from app.buffer.processor import process_buffered_messages

    for lead in ({"id": "lead-1", "phone": "5511999999999", "ai_enabled": True}, _lead(False)):
        with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
             patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
             patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
             patch("app.buffer.processor.get_or_create_conversation", return_value={
                 "id": "conv-1", "status": "active", "stage": "secretaria"
             }) as mock_conv, \
             patch("app.buffer.processor._resolve_media", return_value=("oi", None, None, None, None)), \
             patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
             patch("app.buffer.processor._wamid_already_processed", return_value=False), \
             patch("app.buffer.processor.save_message") as mock_save, \
             patch("app.buffer.processor.run_agent", return_value=None), \
             patch("app.buffer.processor.get_supabase"), \
             patch("app.buffer.processor._update_last_msg"):
            await process_buffered_messages(
                "5511999999999", "oi", "chan-uuid", wamid="wamid_livre_1"
            )

        mock_conv.assert_called_once()
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_lead_normal_segue_o_fluxo_ate_o_agente():
    """Caminho feliz completo: conversa, mensagem salva e agente chamado."""
    from app.buffer.processor import process_buffered_messages

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.buffer.processor.get_or_create_lead", return_value=_lead(False)), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel()), \
         patch("app.buffer.processor.get_provider", return_value=mock_provider), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }) as mock_conv, \
         patch("app.buffer.processor._resolve_media", return_value=("oi", None, None, None, None)), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=False), \
         patch("app.buffer.processor.save_message", return_value={"id": "msg-1"}) as mock_save, \
         patch("app.buffer.processor.run_agent", return_value="Olá!") as mock_agent, \
         patch("app.buffer.processor.get_supabase", return_value=MagicMock()), \
         patch("app.buffer.processor._update_last_msg"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.pop_deferred_media", return_value=[]):
        await process_buffered_messages(
            "5511999999999", "oi", "chan-uuid", wamid="wamid_livre_2"
        )

    mock_conv.assert_called_once()
    mock_save.assert_called()
    mock_agent.assert_called()

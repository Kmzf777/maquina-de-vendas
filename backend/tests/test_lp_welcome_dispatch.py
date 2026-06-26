"""Tests for _process_lp_welcome: named-param template + anti-loop on Meta rejection.

Regression for the 02/06 incident (manual_audit_cancel_loop_infinito):
- Os templates lp_* aprovados usam o param NOMEADO {{primeiro_nome}}. O handler
  enviava um param POSICIONAL → a Meta rejeita. A rejeição volta como HTTP 200 com
  erro embutido, que MetaCloudClient transforma em RuntimeError (não httpx.HTTPStatusError).
  Isso escapava do branch de cancelamento e caía no `except Exception: return` genérico
  → job ficava pending e era re-tentado para sempre (loop infinito).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


def _make_lp_welcome_job(**overrides):
    job = {
        "id": "job-lp-1",
        "conversation_id": "conv-lp-1",
        "lead_id": "lead-1",
        "channel_id": "6e51629d-f095-4a4e-9e26-46a8da225a89",
        "sequence": 1,
        "job_type": "lp_welcome",
        "leads": {
            "id": "lead-1",
            "phone": "5531973117463",
            "name": "Wellington Souza",
            "wa_id": None,
            "last_customer_message_at": None,
        },
        "channels": {
            "id": "6e51629d-f095-4a4e-9e26-46a8da225a89",
            "name": "NUMERO VALERIA",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "1079773125220705", "access_token": "tok"},
            "mode": "ai",
        },
        # Lead ainda não respondeu neste canal (guard lead_already_replied não dispara).
        "conversations": {"id": "conv-lp-1", "stage": "pending", "last_customer_message_at": None},
        "metadata": {
            "lead_phone": "5531973117463",
            "lead_name": "Wellington Souza",
            "template_name": "lp_solicitacao_recebida",
            "language_code": "pt_BR",
            "origem": "terceirizacao",
        },
    }
    job.update(overrides)
    return job


@pytest.mark.asyncio
async def test_lp_welcome_sends_named_primeiro_nome_param():
    """O template lp_solicitacao_recebida usa {{primeiro_nome}} (param NOMEADO).
    O handler DEVE emitir parameter_name='primeiro_nome' com o primeiro nome do lead —
    enviar posicional faz a Meta rejeitar (causa do loop de 02/06)."""
    job = _make_lp_welcome_job()

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.lp1"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.create_deal"), \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler.save_message") as mock_save, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_called_once_with(
        "5531973117463", "lp_solicitacao_recebida",
        components=[{
            "type": "body",
            "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": "Wellington"}],
        }],
        language_code="pt_BR",
    )
    mock_sent.assert_called_once_with("job-lp-1")
    mock_cancel.assert_not_called()
    # 1A: o disparo LP deve ser persistido em messages para reações/replies resolverem.
    # save_message DEVE ser chamado por KEYWORD (o bug da "mensagem fantasma" era passar
    # conversation_id no slot posicional de lead_id → violava a FK e a persistência falhava).
    mock_save.assert_called_once()
    _args, _kwargs = mock_save.call_args
    assert _kwargs.get("lead_id") == "lead-1"
    assert _kwargs.get("role") == "assistant"
    # Eixo 2a: o conteúdo NÃO pode vazar o placeholder cru do sistema (nome do template
    # nem "[disparo automático ...]") — isso poluía o CRM e o campaign_message do LLM.
    _content = _kwargs.get("content", "")
    assert "lp_solicitacao_recebida" not in _content
    assert "disparo automático" not in _content
    assert "Wellington" in _content  # corpo limpo e personalizado
    # A intenção do disparo é carimbada em metadata.dispatch p/ a resolução de persona.
    assert _kwargs.get("metadata", {}).get("dispatch", {}).get("intent") == "warm_lp"
    assert _kwargs.get("conversation_id") == "conv-lp-1"
    assert _kwargs.get("sent_by") == "broadcast"
    assert _kwargs.get("wamid") == "wamid.lp1"


@pytest.mark.asyncio
async def test_lp_welcome_nao_persiste_mensagem_em_rejeicao():
    """Se a Meta rejeita (RuntimeError), NÃO deve persistir mensagem (o disparo não ocorreu)."""
    job = _make_lp_welcome_job()
    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(side_effect=RuntimeError("rejected"))

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.create_deal"), \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler.save_message") as mock_save, \
         patch("app.follow_up.scheduler._mark_sent"), \
         patch("app.follow_up.scheduler._cancel_job"):

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_lp_welcome_cancels_on_meta_rejection_instead_of_looping():
    """Rejeição permanente da Meta vem como RuntimeError (HTTP 200 + erro embutido).
    O job DEVE ser cancelado (meta_rejected), nunca deixado pending para re-tentar
    eternamente — esse era o loop infinito que foi cancelado na mão em 02/06."""
    job = _make_lp_welcome_job()

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(
        side_effect=RuntimeError("Meta send_template rejected (missing messages in response)")
    )

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler.create_deal") as mock_deal, \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-lp-1", "meta_rejected")
    mock_sent.assert_not_called()
    # Rejeição não pode criar card de CRM (o disparo não aconteceu).
    mock_deal.assert_not_called()

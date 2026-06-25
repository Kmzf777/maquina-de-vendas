"""Guardrail de sanidade do follow-up — auditoria do lead 5561984336980 (Daniel), 2026-06-24.

Bug real: o LLM (gemini) RECUSOU gerar o follow-up e escreveu um meta-comentário
("Não é apropriado enviar uma mensagem de follow-up neste caso. O lead informou que
já conversa com um humano da equipe..."). O `process_due_followups` só validava
`if not message` (vazio), então o texto cru da recusa foi ENVIADO ao cliente.

Blindagem: se a saída do LLM tem cara de meta-comentário/recusa, abortar SILENCIOSAMENTE
(cancelar o job, NÃO enviar). Defesa source-agnostic — pega qualquer recusa, qualquer modelo.
"""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


# Texto EXATO vazado para o Daniel (auditoria 2026-06-24).
DANIEL_LEAK = (
    "Não é apropriado enviar uma mensagem de follow-up neste caso. O lead informou que "
    "já conversa com um humano da equipe e que o atendimento atual é feito por uma IA, e "
    "sua última mensagem foi um agradecimento."
)


def _make_job():
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "id": "job-meta-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {"id": "lead-1", "phone": "+5561984336980", "last_customer_message_at": now_iso},
        "channels": {
            "id": "ch-1", "name": "Canal Comercial", "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"}, "mode": "ai",
        },
        "conversations": {
            "id": "conv-1", "stage": "atacado", "followup_enabled": True,
            "last_customer_message_at": now_iso,
        },
    }


def _sb_with_history():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"role": "user", "content": "Já converso com um humano da sua empresa. Obrigado"},
    ]
    return sb


# --- Unit: detector de meta-comentário ------------------------------------

def test_is_meta_comment_detecta_recusa_do_daniel():
    from app.follow_up.scheduler import _is_meta_comment
    assert _is_meta_comment(DANIEL_LEAK) is True


@pytest.mark.parametrize("texto", [
    "Não é apropriado enviar essa mensagem.",
    "Como uma IA, não posso enviar follow-up agora.",
    "Desculpe, mas o lead informou que já tem atendimento.",
    "Não posso gerar uma mensagem de follow-up neste caso.",
    "nao seria adequado enviar uma mensagem de followup",
])
def test_is_meta_comment_detecta_variacoes(texto):
    from app.follow_up.scheduler import _is_meta_comment
    assert _is_meta_comment(texto) is True


@pytest.mark.parametrize("texto", [
    "vi que voce tava olhando o cafe especial pro seu negocio\n\nconseguiu pensar sobre o pedido minimo?",
    "lembrei daquela duvida do prazo de entrega\n\nfaz sentido a gente fechar essa semana?",
    "Oi, tudo bem?",
])
def test_is_meta_comment_nao_marca_followup_legitimo(texto):
    from app.follow_up.scheduler import _is_meta_comment
    assert _is_meta_comment(texto) is False


# --- Integração: process_due_followups aborta sem enviar -------------------

@pytest.mark.asyncio
async def test_meta_comment_aborta_e_nao_envia():
    job = _make_job()
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=_sb_with_history()), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value=(DANIEL_LEAK, "stop")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_called_once_with("job-meta-1", "meta_comment")
        mock_sent.assert_not_called()
        mock_provider.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_followup_legitimo_e_enviado():
    job = _make_job()
    legit = "vi que voce tava vendo o cafe especial pro seu negocio\n\nconseguiu pensar sobre o pedido minimo?"
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=_sb_with_history()), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value=(legit, "stop")):
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_not_called()
        mock_sent.assert_called_once_with("job-meta-1")
        mock_provider.send_text.assert_called_once()

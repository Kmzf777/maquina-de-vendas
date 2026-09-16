"""Duas guardas pequenas no motor de cadencias (engine.py), 11/09/2026.

Contexto: `campaign_enrollments` = 0 linhas em toda a historia — o motor nunca rodou em
producao. Isso quer dizer que estes dois defeitos nunca apareceram em campo, mas tambem
que o primeiro log que o operador vai confiar, quando o motor comecar a rodar, precisa
estar certo. Log mentiroso num motor que acabou de estrear e pior que log ausente: log
ausente e uma pergunta em aberto, log "done" errado e uma resposta errada em que alguem
vai confiar.

1) `send_text` (texto livre) nunca teve a checagem de blacklist que o no `send` (template)
   ganhou em 25/06/2026 — ver test_blacklist_outbound_guard_2026_06_25.py e
   app/campaigns/worker.py::_execute_send_node (camada 2, guardrail no instante do envio).
   Sem a mesma guarda em `_execute_send_text`, um lead que pediu para sair (opt_out ou
   card movido para a pipeline Blacklist) continuava recebendo texto livre da cadencia
   assim que o no fosse `send_text` em vez de `send`.

2) `_execute_action` sempre devolvia `None` implicitamente, inclusive nos `return`
   antecipados por falta de alvo (deal inexistente, tag nao encontrada, round-robin sem
   usuarios cadastrados...). O dispatch de `_process_one` gravava `"acao X executada"`
   com status "done" incondicionalmente — o operador via um check verde no log de
   execucao exatamente onde nada tinha acontecido.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.automation import engine

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------
# send_text × blacklist
# --------------------------------------------------------------------------------------

def _mock_sb_for_send_text():
    """Supabase mock que satisfaz _conversation_window (sem conversa = sem janela
    conhecida, nao bloqueia) e _resolve_channel (canal existe)."""
    sb = MagicMock()
    # channels: .select().eq().limit().execute().data  (1 eq)
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "ch-1", "provider": "meta"}
    ]
    # conversations: .select().eq().eq().limit().execute().data  (2 eq)
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    return sb


ENROLLMENT = {"id": "e1", "lead_id": "lead-1"}
SEND_TEXT_NODE = {"id": "n1", "type": "send_text", "config": {"message_text": "oi", "channel_id": "ch-1"}}
LEAD = {"id": "lead-1", "phone": "5511999999999"}
CAMPAIGN = {"channel_id": "ch-1"}


class TestSendTextBlacklist:
    async def test_nao_envia_quando_lead_esta_na_blacklist(self):
        sb = _mock_sb_for_send_text()
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        with (
            patch.object(engine, "get_supabase", return_value=sb),
            patch("app.whatsapp.registry.get_provider", return_value=mock_provider),
            patch("app.leads.service.is_lead_blacklisted", return_value=True) as mock_bl,
            patch("app.leads.service.save_message") as mock_save,
        ):
            await engine._execute_send_text(ENROLLMENT, SEND_TEXT_NODE, LEAD, NOW, CAMPAIGN)

        mock_bl.assert_called_once_with("lead-1")
        mock_provider.send_text.assert_not_called()
        mock_save.assert_not_called()

    async def test_envia_quando_lead_nao_esta_na_blacklist(self):
        sb = _mock_sb_for_send_text()
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        with (
            patch.object(engine, "get_supabase", return_value=sb),
            patch("app.whatsapp.registry.get_provider", return_value=mock_provider),
            patch("app.leads.service.is_lead_blacklisted", return_value=False),
            patch("app.leads.service.save_message") as mock_save,
        ):
            await engine._execute_send_text(ENROLLMENT, SEND_TEXT_NODE, LEAD, NOW, CAMPAIGN)

        mock_provider.send_text.assert_awaited_once_with(LEAD["phone"], "oi")
        mock_save.assert_called_once()


# --------------------------------------------------------------------------------------
# ação sem alvo → "skipped", ação que agiu → "done"
# --------------------------------------------------------------------------------------

ACTION_NODE = {
    "id": "n-action",
    "type": "action",
    "next_node_id": None,
    "config": {"action_type": "add_tag", "tag_name": "vip"},
}

ACTION_ENROLLMENT = {
    "id": "e-action",
    "lead_id": "lead-1",
    "step_count": 0,
    "leads": {"id": "lead-1", "phone": "5511999", "ai_enabled": True},
    "campaigns": {"id": "c1", "status": "active", "audience": "ia"},
    "campaign_nodes": ACTION_NODE,
    "metadata": {},
}


def _rodar_action(execute_action_return: bool):
    """Executa _process_one num nó `action`, com `_execute_action` mockado para devolver
    `execute_action_return`, e devolve a lista de chamadas a `_log_exec`."""
    log_calls = []
    with (
        patch.object(engine, "_execute_action", return_value=execute_action_return) as mock_exec,
        patch.object(engine, "_log_exec", side_effect=lambda *a, **kw: log_calls.append(a)),
        patch.object(engine, "_complete") as mock_complete,
        patch.object(engine, "_update") as mock_update,
        patch.object(engine, "_guard_broken", return_value=False),
        patch.object(engine, "_conversation_followup_disabled", return_value=False),
        patch.object(engine, "_audience_allows", return_value=True),
    ):
        asyncio.run(engine._process_one(dict(ACTION_ENROLLMENT), NOW))
    return log_calls, mock_exec


class TestAcaoSemAlvoLogaSkipped:
    def test_acao_sem_alvo_loga_skipped_nao_done(self):
        log_calls, mock_exec = _rodar_action(False)
        mock_exec.assert_called_once()
        assert log_calls, "_log_exec não foi chamado para o nó action"
        status = log_calls[-1][2]
        assert status == "skipped", f"ação sem alvo deveria logar 'skipped', logou {status!r}"

    def test_acao_que_agiu_loga_done(self):
        log_calls, mock_exec = _rodar_action(True)
        mock_exec.assert_called_once()
        assert log_calls, "_log_exec não foi chamado para o nó action"
        status = log_calls[-1][2]
        assert status == "done", f"ação que agiu deveria logar 'done', logou {status!r}"

"""get_history (conversations e leads) preenche content vazio de mídia com placeholder.

Trilha A da auditoria 10/07: mensagens de mídia do vendedor gravavam content="" —
LLM (orchestrator), dossiê (memory_manager) e QA (tools de transcrição) ficavam
cegos ao que foi enviado. Ambos os get_history devem mapear content vazio +
message_type de mídia para um placeholder textual, preservando texto normal intocado.
"""
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# app.conversations.service.get_history
# ---------------------------------------------------------------------------

def _make_conv_sb_mock(rows):
    execute_result = MagicMock()
    execute_result.data = rows

    limit_mock = MagicMock()
    limit_mock.execute.return_value = execute_result

    order_mock = MagicMock()
    order_mock.limit.return_value = limit_mock

    eq_mock = MagicMock()
    eq_mock.order.return_value = order_mock

    select_mock = MagicMock()
    select_mock.eq.return_value = eq_mock

    table_mock = MagicMock()
    table_mock.select.return_value = select_mock

    sb = MagicMock()
    sb.table.return_value = table_mock
    return sb


def test_conversations_get_history_audio_row_gets_placeholder():
    from app.conversations.service import get_history

    rows_desc = [
        {
            "role": "assistant",
            "content": "",
            "stage": "secretaria",
            "created_at": "2026-07-10T10:00:00",
            "wamid": None,
            "quoted_wamid": None,
            "message_type": "audio",
            "metadata": None,
            "sent_by": "seller",
        },
    ]
    sb = _make_conv_sb_mock(rows_desc)

    with patch("app.conversations.service.get_supabase", return_value=sb):
        result = get_history("conv-audio")

    assert result[0]["content"] == "[áudio]"


def test_conversations_get_history_text_row_unchanged():
    from app.conversations.service import get_history

    rows_desc = [
        {
            "role": "user",
            "content": "oi tudo bem?",
            "stage": "secretaria",
            "created_at": "2026-07-10T10:00:00",
            "wamid": "wamid.abc",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
            "sent_by": None,
        },
    ]
    sb = _make_conv_sb_mock(rows_desc)

    with patch("app.conversations.service.get_supabase", return_value=sb):
        result = get_history("conv-text")

    assert result[0]["content"] == "oi tudo bem?"


# ---------------------------------------------------------------------------
# app.leads.service.get_history
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self.select_arg = None

    def select(self, arg, *a, **k):
        self.select_arg = arg
        return self

    def eq(self, *a, **k):
        return self

    def gt(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.query = None

    def table(self, name):
        self.query = _Query(self._rows)
        return self.query


def test_leads_get_history_audio_row_gets_placeholder():
    from app.leads.service import get_history

    rows = [
        {
            "role": "assistant",
            "content": "",
            "stage": "secretaria",
            "created_at": "2026-07-10T10:00:00",
            "message_type": "audio",
        },
    ]
    sb = _FakeSupabase(rows)

    with patch("app.leads.service.get_supabase", return_value=sb):
        result = get_history("lead-audio")

    assert result[0]["content"] == "[áudio]"


def test_leads_get_history_text_row_unchanged():
    from app.leads.service import get_history

    rows = [
        {
            "role": "user",
            "content": "quero saber o preco",
            "stage": "secretaria",
            "created_at": "2026-07-10T10:00:00",
            "message_type": "text",
        },
    ]
    sb = _FakeSupabase(rows)

    with patch("app.leads.service.get_supabase", return_value=sb):
        result = get_history("lead-text")

    assert result[0]["content"] == "quero saber o preco"


def test_leads_get_history_selects_message_type_column():
    """get_history precisa buscar message_type do banco para conseguir mapear o
    placeholder — sem essa coluna no select, o helper nunca vê o message_type."""
    from app.leads.service import get_history

    sb = _FakeSupabase([])
    with patch("app.leads.service.get_supabase", return_value=sb):
        get_history("lead-x")

    assert "message_type" in sb.query.select_arg

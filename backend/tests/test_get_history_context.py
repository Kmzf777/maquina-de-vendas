"""
Tests that get_history (conversations/service.py) requests and returns the
extended set of columns needed by the agent orchestrator for reply/reaction
context: wamid, quoted_wamid, message_type, metadata.
"""
import pytest
from unittest.mock import patch, MagicMock


def _make_sb_mock(rows):
    """Build a MagicMock that mimics the Supabase chained-call interface
    used by get_history:
      sb.table().select().eq().order().limit().execute() -> result
    The mock also captures the argument passed to .select() so we can assert it.
    """
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

    # Expose internals for assertion
    sb._table_mock = table_mock
    sb._select_mock = select_mock

    return sb


def test_get_history_select_includes_new_columns():
    """get_history deve solicitar wamid, quoted_wamid, message_type e metadata
    na query ao Supabase."""
    from app.conversations.service import get_history

    sb = _make_sb_mock([])

    with patch("app.conversations.service.get_supabase", return_value=sb):
        get_history("conv-test-001")

    # Verify .select() was called exactly once
    sb._table_mock.select.assert_called_once()
    call_arg = sb._table_mock.select.call_args[0][0]

    for col in ("wamid", "quoted_wamid", "message_type", "metadata"):
        assert col in call_arg, (
            f"get_history deveria selecionar a coluna '{col}', "
            f"mas o argumento de select() foi: {call_arg!r}"
        )

    # Also confirm the original columns are still present
    for col in ("role", "content", "stage", "created_at"):
        assert col in call_arg, (
            f"get_history não deve remover a coluna '{col}', "
            f"mas o argumento de select() foi: {call_arg!r}"
        )


def test_get_history_returns_rows_with_new_fields():
    """get_history busca as mais recentes (desc) e reverte para ordem cronológica
    ascendente; deve retornar as linhas nessa ordem, com os novos campos preservados.
    O mock simula o fetch real (desc = mais novo primeiro), então alimentamos as linhas
    em ordem decrescente; após o reverse interno, o resultado volta a `sample_rows`."""
    from app.conversations.service import get_history

    sample_rows = [
        {
            "role": "user",
            "content": "Oi",
            "stage": "secretaria",
            "created_at": "2026-06-15T10:00:00",
            "wamid": "wamid.HBgLNTUxMTk5OTk=",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        },
        {
            "role": "assistant",
            "content": "Olá!",
            "stage": "secretaria",
            "created_at": "2026-06-15T10:00:05",
            "wamid": "wamid.HBgLNTUxMTk5OTk=_2",
            "quoted_wamid": "wamid.HBgLNTUxMTk5OTk=",
            "message_type": "text",
            "metadata": {"some_key": "val"},
        },
    ]

    # DB com desc=True devolve o mais novo primeiro; get_history reverte p/ ascendente.
    sb = _make_sb_mock(list(reversed(sample_rows)))

    with patch("app.conversations.service.get_supabase", return_value=sb):
        result = get_history("conv-test-002", limit=10)

    assert result == sample_rows, (
        "get_history deveria retornar as linhas em ordem cronológica ascendente"
    )
    assert result[0]["wamid"] == "wamid.HBgLNTUxMTk5OTk="
    assert result[1]["quoted_wamid"] == "wamid.HBgLNTUxMTk5OTk="
    assert result[1]["metadata"] == {"some_key": "val"}


def test_get_history_default_limit_unchanged():
    """O limit padrão de get_history deve continuar sendo 30."""
    from app.conversations.service import get_history
    import inspect

    sig = inspect.signature(get_history)
    default_limit = sig.parameters["limit"].default
    assert default_limit == 30, (
        f"O limit padrão de get_history deveria ser 30, mas é {default_limit}"
    )

"""Eixo MENSAL do budget_guard (27/07/2026) — o alerta que faltou no apagão de 5 dias.

Contexto: entre 19 e 27/07 a Valéria ficou muda porque o teto de gasto MENSAL do Google
AI Studio estourou. O kill-switch diário (US$8/dia) nunca viu nada — o gasto de cada dia
ficava em US$1-3. Um teto mensal é atingido pela SOMA, não pelo pico, então precisava de
um eixo próprio. Sem ele o estouro só é percebido quando a IA já parou de responder.

Invariantes travados aqui:
  1. O limiar nasce ARMADO (default US$40) — nascer desarmado já custou ~R$149 antes.
  2. Cruzou o limiar => alerta dispara UMA vez no mês (dedup).
  3. Abaixo do limiar => silêncio absoluto.
  4. Fail-open: erro de leitura devolve 0.0 e nunca bloqueia o atendimento.
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _reset_state():
    from app.agent import budget_guard
    budget_guard._month_cache.update(month=None, spend=0.0, at=0.0)
    budget_guard._alert_state["monthly_month"] = None
    yield
    budget_guard._month_cache.update(month=None, spend=0.0, at=0.0)
    budget_guard._alert_state["monthly_month"] = None


def test_limiar_nasce_armado(monkeypatch):
    """Lição do FinOps P0: guard que nasce desarmado não protege ninguém."""
    from app.agent import budget_guard
    monkeypatch.delenv("LLM_MONTHLY_ALERT_USD", raising=False)
    assert budget_guard.monthly_alert_limit_usd() == 40.0


def test_zero_explicito_desliga(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_MONTHLY_ALERT_USD", "0")
    assert budget_guard.monthly_alert_limit_usd() == 0.0

    with patch.object(budget_guard, "month_spend_usd") as spend:
        budget_guard.check_monthly_budget()
        spend.assert_not_called()


def test_valor_invalido_nao_quebra(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_MONTHLY_ALERT_USD", "quarenta")
    assert budget_guard.monthly_alert_limit_usd() == 0.0


def test_cruzou_limiar_dispara_alerta_uma_vez(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_MONTHLY_ALERT_USD", "40")

    with patch.object(budget_guard, "month_spend_usd", return_value=45.0), \
         patch.object(budget_guard, "_fire_alert_deduped") as fire:
        budget_guard.check_monthly_budget()
        budget_guard.check_monthly_budget()  # segunda passagem no mesmo mês
        budget_guard.check_monthly_budget()

    assert fire.call_count == 1, "alerta mensal duplicou dentro do mesmo mês"
    args = fire.call_args[0]
    assert args[0] == "llm_monthly_budget_warning"
    assert args[1] == "warning"


def test_abaixo_do_limiar_fica_em_silencio(monkeypatch):
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_MONTHLY_ALERT_USD", "40")

    with patch.object(budget_guard, "month_spend_usd", return_value=21.58), \
         patch.object(budget_guard, "_fire_alert_deduped") as fire:
        budget_guard.check_monthly_budget()

    fire.assert_not_called()


def test_mensagem_do_alerta_aponta_a_acao(monkeypatch):
    """O alerta precisa ser autossuficiente: onde olhar e o que ajustar."""
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_MONTHLY_ALERT_USD", "40")

    with patch.object(budget_guard, "month_spend_usd", return_value=45.0), \
         patch.object(budget_guard, "_fire_alert_deduped") as fire:
        budget_guard.check_monthly_budget()

    mensagem = fire.call_args[0][3]
    assert "ai.studio/spend" in mensagem
    assert "LLM_MONTHLY_ALERT_USD" in mensagem


def test_leitura_do_mes_e_fail_open():
    """Medidor quebrado não pode bloquear atendimento — devolve 0.0 e segue."""
    from app.agent import budget_guard
    with patch.object(budget_guard, "get_supabase", side_effect=RuntimeError("db fora")):
        assert budget_guard.month_spend_usd(force=True) == 0.0


def test_soma_o_mes_e_usa_cache():
    from app.agent import budget_guard
    sb = MagicMock()
    sb.table.return_value.select.return_value.gte.return_value.execute.return_value = MagicMock(
        data=[{"total_cost": 10.0}, {"total_cost": 11.58}]
    )
    with patch.object(budget_guard, "get_supabase", return_value=sb) as get_sb:
        primeiro = budget_guard.month_spend_usd(force=True)
        segundo = budget_guard.month_spend_usd()  # deve vir do cache

    assert primeiro == pytest.approx(21.58)
    assert segundo == pytest.approx(21.58)
    assert get_sb.call_count == 1, "query do mês rodou duas vezes (cache não segurou)"


def test_check_monthly_e_fail_soft_dentro_do_guard(monkeypatch):
    """is_exceeded não pode quebrar se a rotina mensal explodir."""
    from app.agent import budget_guard
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "8")

    with patch.object(budget_guard, "today_spend_usd", return_value=1.0), \
         patch.object(budget_guard, "check_monthly_budget", side_effect=RuntimeError("boom")):
        assert budget_guard.is_exceeded() is False

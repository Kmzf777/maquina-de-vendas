"""TDD Onda 2: QA diário de aderência no watchdog (relatório D-1 em system_alerts).

As guardas da Onda 1 (pergunta repetida, prompt echo, autoresponder, hot-lead/dedup
de template) produzem sinais espalhados em 4 tabelas — ninguém olha tudo isso por
conversa. O check diário consolida o dia anterior num alerta informativo
(`daily_qa_report`): quantas respostas a IA deu, quantos handoffs/opt-outs, quantas
correções de pergunta repetida, quantos dossiês atualizados, quantos disparos.
Publica 1x/dia entre 07:00-08:00 BRT; fora da janela nem toca o banco.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import app.watchdog.service as WD


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_fora_da_janela_nao_toca_o_banco():
    # 12:00 BRT = 15:00 UTC — fora da janela 07-08h BRT
    with patch.object(WD, "get_supabase") as m_sb, \
         patch.object(WD, "create_system_alert") as m_alert:
        assert WD.check_daily_qa(_utc(2026, 7, 9, 15, 0)) is False
    m_sb.assert_not_called()
    m_alert.assert_not_called()


def test_dedup_do_dia_nao_republica():
    # 07:30 BRT = 10:30 UTC — dentro da janela, mas já publicado hoje
    with patch.object(WD, "_qa_already_published_today", return_value=True), \
         patch.object(WD, "_qa_collect_metrics") as m_collect, \
         patch.object(WD, "create_system_alert") as m_alert:
        assert WD.check_daily_qa(_utc(2026, 7, 9, 10, 30)) is False
    m_collect.assert_not_called()
    m_alert.assert_not_called()


def test_publica_relatorio_com_metricas():
    metrics = {
        "respostas_ia": 42, "followups_enviados": 4, "inbounds": 30, "handoffs": 3,
        "optouts": 1, "perguntas_repetidas_corrigidas": 2, "dossies_atualizados": 12,
        "disparos_enviados": 50, "numero_errado_marcados": 1, "indicacoes": 1,
    }
    with patch.object(WD, "_qa_already_published_today", return_value=False), \
         patch.object(WD, "_qa_collect_metrics", return_value=metrics), \
         patch.object(WD, "create_system_alert") as m_alert:
        assert WD.check_daily_qa(_utc(2026, 7, 9, 10, 15)) is True

    m_alert.assert_called_once()
    args, kwargs = m_alert.call_args
    assert args[0] == "daily_qa_report"
    assert kwargs.get("severity") == "info"
    assert kwargs.get("metadata", {}).get("metrics") == metrics
    # o corpo carrega os números-chave em texto legível
    assert "42" in args[2] and "3" in args[2]


def test_metricas_fail_soft_por_indicador():
    """Uma query quebrada não derruba o relatório: o indicador vira -1."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch.object(WD, "get_supabase", return_value=sb):
        metrics = WD._qa_collect_metrics(_utc(2026, 7, 9, 10, 15))
    assert metrics  # dict com todas as chaves
    assert all(v == -1 for v in metrics.values())

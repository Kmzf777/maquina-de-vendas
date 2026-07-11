"""Trilha B / B4 — métrica de guarda de handoff verbalizado no relatório diário de QA.

A guarda determinística de handoff verbalizado (orchestrator ~L1381) força encaminhar_humano
quando o texto final anuncia a transferência mas nenhuma tool foi chamada. Ela grava um
marcador system com motivo contendo "handoff verbalizado sem tool-call". Queremos MEDIR a
frequência diária dessa guarda no daily_qa_report — sem alargar o LIKE de handoffs existente
(lição do repo: handoffs são contados por marcador estreito 'Lead encaminhado%'; contagem
própria e separada).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import app.watchdog.service as WD


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class _Q:
    """Query builder falso que registra (tabela, filtros eq, padrão like) e devolve count."""

    def __init__(self, table, log):
        self.table_name = table
        self.log = log
        self.eqs = {}
        self.like_pat = None

    def select(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lt(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **k):
        return self

    def eq(self, k, v):
        self.eqs[k] = v
        return self

    def like(self, column, pat):
        self.like_pat = pat
        return self

    def execute(self):
        self.log.append((self.table_name, dict(self.eqs), self.like_pat))
        m = MagicMock()
        m.count = 7 if (self.like_pat and "handoff verbalizado sem tool-call" in self.like_pat) else 0
        m.data = []
        return m


class _SB:
    def __init__(self, log):
        self.log = log

    def table(self, name):
        return _Q(name, self.log)


def test_metrica_conta_marcador_de_handoff_verbalizado():
    log = []
    with patch.object(WD, "get_supabase", return_value=_SB(log)):
        metrics = WD._qa_collect_metrics(_utc(2026, 7, 10, 10, 15))

    assert metrics["handoffs_verbalizados"] == 7
    # Contagem PRÓPRIA: role=system + marcador verbal, sem reaproveitar o LIKE de 'Lead encaminhado%'.
    assert any(
        t == "messages" and e.get("role") == "system"
        and lk and "handoff verbalizado sem tool-call" in lk
        for (t, e, lk) in log
    ), log


def test_resumo_inclui_contagem_de_handoff_verbalizado():
    metrics = {
        "respostas_ia": 42, "followups_enviados": 4, "inbounds": 30, "handoffs": 3,
        "optouts": 1, "perguntas_repetidas_corrigidas": 2, "dossies_atualizados": 12,
        "disparos_enviados": 50, "numero_errado_marcados": 1, "indicacoes": 1,
        "jobs_por_tipo": {}, "handoffs_verbalizados": 9,
    }
    with patch.object(WD, "_qa_already_published_today", return_value=False), \
         patch.object(WD, "_qa_collect_metrics", return_value=metrics), \
         patch.object(WD, "create_system_alert") as m_alert:
        assert WD.check_daily_qa(_utc(2026, 7, 10, 10, 15)) is True

    args, kwargs = m_alert.call_args
    assert "9" in args[2] and "verbaliz" in args[2].lower()
    assert kwargs.get("metadata", {}).get("metrics", {}).get("handoffs_verbalizados") == 9


def test_resumo_tolerante_a_metrics_sem_a_chave_nova():
    # metrics legado/parcial sem a chave não pode quebrar o relatório (.get tolerante).
    metrics = {
        "respostas_ia": 1, "followups_enviados": 0, "inbounds": 1, "handoffs": 0,
        "optouts": 0, "perguntas_repetidas_corrigidas": 0, "dossies_atualizados": 0,
        "disparos_enviados": 0, "numero_errado_marcados": 0, "indicacoes": 0,
    }
    with patch.object(WD, "_qa_already_published_today", return_value=False), \
         patch.object(WD, "_qa_collect_metrics", return_value=metrics), \
         patch.object(WD, "create_system_alert") as m_alert:
        assert WD.check_daily_qa(_utc(2026, 7, 10, 10, 15)) is True
    m_alert.assert_called_once()

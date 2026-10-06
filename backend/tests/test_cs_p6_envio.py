"""P6 / Task 6.2 — o envio relê as vendas e cancela com `lead_comprou`."""
from datetime import timedelta
from types import SimpleNamespace

from app.follow_up import scheduler as S
from tests import test_scheduler_joao_2026_09_18 as T

NOW = T.NOW


def _iso(dias):
    return (NOW - timedelta(days=dias)).isoformat()


def _venda(dias, *, id="s1", status="registrada", lead="lead-1"):
    return {"id": id, "lead_id": lead, "sold_at": _iso(dias), "created_at": _iso(dias),
            "status": status}


class _TabelaVendas:
    def __init__(self, vendas):
        self.vendas, self.lead = vendas, None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        if col == "lead_id":
            self.lead = val
        return self

    def execute(self):
        return SimpleNamespace(data=[v for v in self.vendas if v["lead_id"] == self.lead])


class _ComVendas(T._FakeSupabase):
    def __init__(self, deals, vendas, stages=None, quebra=False):
        super().__init__(deals, stages)
        self.vendas, self.quebra = vendas, quebra

    def table(self, nome):
        if nome == "sales":
            if self.quebra:
                raise RuntimeError("statement timeout")
            return _TabelaVendas(self.vendas)
        return super().table(nome)


def _db(vendas, *, deal_criado_dias=200, quebra=False):
    return _ComVendas(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": S.PIPELINE_JOAO_ATACADO,
                          "stage_id": T.ETAPA_NOVO_ATACADO,
                          "created_at": _iso(deal_criado_dias)}},
        vendas=vendas, quebra=quebra)


def _db_kit(vendas):
    return _ComVendas(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": S.PIPELINE_JOAO_REPOSICAO_ATACADO,
                          "stage_id": T.ETAPA_CLIENTE_ATIVO_REPOSICAO,
                          "created_at": _iso(30)}},
        vendas=vendas, stages=T.ETAPAS_COM_REPOSICAO)


def _job_kit():
    return T._joao_job(job_type="joao_kit", metadata={
        "cadencia": "kit", "funil": "reposicao_atacado", "toque": 2,
        "template_name": "followjoao_kit_2", "matricula_em": _iso(7)})


def test_toque_de_prospeccao_e_cancelado_quando_o_lead_comprou():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(2)]))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")
    calls["meta"].send_template.assert_not_awaited()


def test_venda_depois_da_criacao_do_card_cancela_mesmo_antiga():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(60)], deal_criado_dias=90))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")


def test_sem_venda_o_toque_sai():
    calls = T._run_handler(T._joao_job(), sb=_db([]))
    calls["meta"].send_template.assert_awaited_once()
    calls["cancel"].assert_not_called()


def test_venda_cancelada_nao_segura_o_toque():
    calls = T._run_handler(T._joao_job(), sb=_db([_venda(2, status="cancelada")]))
    calls["meta"].send_template.assert_awaited_once()


def test_falha_ao_ler_vendas_adia_sem_estado_terminal():
    calls = T._run_handler(T._joao_job(), sb=_db([], quebra=True))
    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_not_called()
    calls["sent"].assert_not_called()


def test_kit_cancela_se_o_lead_comprou_depois_da_matricula():
    calls = T._run_handler(_job_kit(), sb=_db_kit([_venda(27, id="kit"), _venda(1, id="nova")]))
    calls["cancel"].assert_called_once_with("job-joao-1", "lead_comprou")
    calls["meta"].send_template.assert_not_awaited()


def test_kit_sem_compra_nova_sai():
    calls = T._run_handler(_job_kit(), sb=_db_kit([_venda(27, id="kit")]))
    calls["meta"].send_template.assert_awaited_once()


def test_reposicao_nao_e_afetada_pela_regra():
    job = T._joao_job(job_type="joao_reposicao", metadata={
        "cadencia": "reposicao", "funil": "reposicao_atacado", "toque": 2,
        "template_name": "joao_reposicao_atacado_t2"})
    calls = T._run_handler(job, sb=_db_kit([_venda(1)]))
    calls["meta"].send_template.assert_awaited_once()

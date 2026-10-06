"""P6 / Task 6.1 e 6.4 — quem comprou não recebe prospecção; o kit só pega kit."""
from datetime import datetime, timedelta, timezone

import pytest

from app.follow_up import service as S

NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
PROPOSTA = S.resolver_para_agendar("atacado", "proposta", {})
KIT = S.resolver_para_agendar("reposicao_atacado", "kit", {"ativa": True})


def _venda(dias_atras, *, id="s1", status="registrada", kit=None, **extra):
    quando = (NOW - timedelta(days=dias_atras)).isoformat()
    v = {"id": id, "lead_id": "lead-1", "sold_at": quando, "created_at": quando,
         "status": status, **extra}
    if kit is not None:
        v["kit"] = kit
    return v


def _pular(cad, vendas, *, deal_dias=None, dias=30, jobs=()):
    criado = None if deal_dias is None else NOW - timedelta(days=deal_dias)
    return S.motivo_para_pular_joao(cad, list(jobs), NOW, vendas=vendas,
                                    deal_criado_em=criado, dias_sem_prospeccao=dias)


# ── prospecção ────────────────────────────────────────────────────────────────
def test_caso_real_joao_proposta_para_lead_com_venda_manual_em_outro_deal():
    venda = _venda(3, deal_id="deal-de-outro-card", origin="manual")
    assert _pular(PROPOSTA, [venda], deal_dias=10) == "lead_comprou"


@pytest.mark.parametrize("funil,codigo", [
    ("atacado", "novo"), ("private_label", "em_conversa"), ("private_label", "proposta")])
def test_venda_recente_pula_as_tres_de_prospeccao(funil, codigo):
    cad = S.resolver_para_agendar(funil, codigo, {})
    assert _pular(cad, [_venda(29)], deal_dias=200) == "lead_comprou"


def test_venda_depois_da_criacao_do_card_pula_mesmo_fora_dos_n_dias():
    assert _pular(PROPOSTA, [_venda(60)], deal_dias=90) == "lead_comprou"


def test_venda_antiga_anterior_ao_card_nao_pula():
    assert _pular(PROPOSTA, [_venda(60)], deal_dias=40) is None


def test_venda_cancelada_nao_conta():
    assert _pular(PROPOSTA, [_venda(2, status="cancelada")], deal_dias=10) is None


def test_n_vem_do_ajuste():
    assert _pular(PROPOSTA, [_venda(45)], deal_dias=30, dias=60) == "lead_comprou"
    assert _pular(PROPOSTA, [_venda(45)], deal_dias=30, dias=30) is None


def test_venda_sem_data_na_duvida_pula():
    v = _venda(5)
    v["sold_at"] = v["created_at"] = None
    assert _pular(PROPOSTA, [v], deal_dias=10) == "lead_comprou"


def test_sem_vendas_informadas_a_funcao_pura_nao_aplica_a_regra():
    # O contrato antigo (3 argumentos) continua valendo. A varredura SEMPRE informa.
    assert S.motivo_para_pular_joao(PROPOSTA, [], NOW) is None


def test_reposicao_ignora_a_regra_de_venda():
    rep = S.resolver_para_agendar("reposicao_atacado", "reposicao", {})
    assert _pular(rep, [_venda(1)], deal_dias=1) is None


def test_cadencia_em_andamento_continua_vindo_primeiro():
    pendente = {"id": "j1", "status": "pending", "job_type": "joao_proposta",
                "metadata": {}}
    assert _pular(PROPOSTA, [_venda(1)], deal_dias=5, jobs=[pendente]) == \
        "cadencia_em_andamento"


# ── kit ───────────────────────────────────────────────────────────────────────
def test_kit_ha_20_dias_entra():
    assert _pular(KIT, [_venda(20, kit=True)]) is None


def test_kit_ha_19_dias_nao_entra():
    assert _pular(KIT, [_venda(19, kit=True)]) == "venda_kit_recente"


def test_ultima_venda_nao_kit_nao_entra():
    vendas = [_venda(60, id="a", kit=True), _venda(25, id="b", kit=False)]
    assert _pular(KIT, vendas) == "ultima_venda_nao_e_kit"


def test_kit_depois_de_uma_venda_normal_entra():
    vendas = [_venda(90, id="a", kit=False), _venda(21, id="b", kit=True)]
    assert _pular(KIT, vendas) is None


def test_kit_cancelado_nao_e_a_ultima_venda():
    vendas = [_venda(60, id="a", kit=False), _venda(25, id="b", kit=True, status="cancelada")]
    assert _pular(KIT, vendas) == "ultima_venda_nao_e_kit"


def test_kit_sem_venda_ou_sem_leitura():
    assert _pular(KIT, []) == "sem_venda"
    assert _pular(KIT, None) == "vendas_desconhecidas"


def test_venda_sem_marca_de_kit_na_duvida_nao_e_kit():
    assert _pular(KIT, [_venda(25)]) == "ultima_venda_nao_e_kit"


def test_kit_respeita_o_gatilho_sobreposto():
    kit30 = S.resolver_para_agendar("reposicao_atacado", "kit",
                                    {"ativa": True, "gatilho_dias": 30})
    assert _pular(kit30, [_venda(25, kit=True)]) == "venda_kit_recente"


def test_kit_que_ja_rodou_respeita_o_cooldown():
    enviado = {"id": "j1", "status": "sent", "job_type": "joao_kit",
               "created_at": (NOW - timedelta(days=10)).isoformat(),
               "metadata": {"matricula_id": "m1"}}
    assert _pular(KIT, [_venda(30, kit=True)], jobs=[enviado]) == "cooldown"


# ── envio do kit ───────────────────────────────────────────────────────────────
def test_comprou_depois_da_matricula():
    matricula = NOW - timedelta(days=7)
    assert S.comprou_depois_da_matricula([_venda(1)], matricula_em=matricula)
    assert not S.comprou_depois_da_matricula([_venda(27, kit=True)], matricula_em=matricula)
    assert not S.comprou_depois_da_matricula(
        [_venda(1, status="cancelada")], matricula_em=matricula)

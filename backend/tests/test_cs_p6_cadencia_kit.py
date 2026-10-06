"""P6 / Task 6.4 — a cadência `kit` existe nos dois funis de Reposição, desligada."""
from unittest.mock import patch

import pytest

from app.follow_up import cadence_joao as C
from app.follow_up import scheduler as SCH
from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import _FakeSupabase

REPOSICAO = ("reposicao_atacado", "reposicao_private_label")


@pytest.mark.parametrize("funil", REPOSICAO)
def test_kit_existe_nos_dois_funis_de_reposicao(funil):
    kit = C.cadencia_do_funil(funil, "kit")
    assert kit is not None
    assert (kit.gatilho_stage_key, kit.gatilho_stage_rotulo) == ("novo", "Cliente Ativo")
    assert kit.gatilho_dias == 20
    assert [t.offset.days for t in kit.touches] == [0, 7]
    assert kit.job_type == "joao_kit"


@pytest.mark.parametrize("funil", ["atacado", "private_label", "recuperacao"])
def test_kit_nao_existe_fora_da_reposicao(funil):
    assert C.cadencia_do_funil(funil, "kit") is None


@pytest.mark.parametrize("funil", REPOSICAO)
def test_kit_nasce_desligado_e_sem_template(funil):
    assert C.resolver(funil, "kit", {}).ativa is False
    assert C.toques_sem_template(funil, "kit") == (1, 2)


def test_kit_nao_move_card_nem_se_repete():
    kit = C.cadencia_do_funil("reposicao_atacado", "kit")
    assert kit.etapa_final_key is None
    assert all(t.move_para is None for t in kit.touches)
    assert kit.etapas_vivas_efetivas == ("novo",)
    assert kit.repete_ultimo is False


def test_ligar_o_kit_pela_sobreposicao_do_banco():
    r = C.resolver("reposicao_atacado", "kit", {
        "ativa": True,
        "toques": {1: {"template_name": "followjoao_kit_1"},
                   2: {"template_name": "followjoao_kit_2"}},
    })
    assert r.ativa is True
    assert [t.template_name for t in r.touches] == ["followjoao_kit_1", "followjoao_kit_2"]


def test_o_contrato_da_tela_nao_muda_e_a_lista_completa_tem_o_kit():
    assert [c.codigo for c in C.funil("reposicao_atacado").cadencias] == \
        ["reposicao", "em_atencao"]
    assert [c.codigo for c in C.cadencias_do_funil("reposicao_atacado")] == \
        ["reposicao", "em_atencao", "kit"]
    assert C.cadencias_do_funil("inexistente") == ()


def test_job_types_todos_e_os_cinco_mais_o_kit():
    assert C.JOB_TYPES_TODOS == C.JOB_TYPES | {"joao_kit"}


def test_service_e_scheduler_enxergam_joao_kit():
    # Sem isto o job de kit escapa do teto diário, da trava de "cadência em andamento" e
    # da trava de "1 template por lead por dia".
    assert "joao_kit" in S.JOAO_JOB_TYPES
    assert "joao_kit" in SCH.JOAO_JOB_TYPES
    assert SCH._stop_reason_applies("ai_disabled", "joao_kit") is False


def test_sobreposicao_do_banco_le_a_linha_do_kit():
    fake = _FakeSupabase(rows={
        "followup_joao_cadencia": [{"funil": "reposicao_atacado", "cadencia": "kit",
                                    "gatilho_dias": None, "ativa": True}],
        "followup_joao_toque": [{"funil": "reposicao_atacado", "cadencia": "kit",
                                 "toque": 1, "dias": None,
                                 "template_name": "followjoao_kit_1"}],
    })
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        ov = S.carregar_overrides_joao()
    assert ov["reposicao_atacado"]["kit"]["ativa"] is True
    assert ov["reposicao_atacado"]["kit"]["toques"][1]["template_name"] == "followjoao_kit_1"

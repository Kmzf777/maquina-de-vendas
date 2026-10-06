"""P6 / Task 6.1 — N vem de `followup_joao_ajustes`, default 30, fail-closed."""
from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import _FakeSupabase


def test_sem_linha_vale_30():
    assert S.carregar_dias_sem_prospeccao_apos_venda(_FakeSupabase(rows={})) == 30


def test_le_a_linha_e_ignora_as_outras_chaves():
    fake = _FakeSupabase(rows={"followup_joao_ajustes": [
        {"chave": "teto_diario_disparos", "valor": 50},
        {"chave": "dias_sem_prospeccao_apos_venda", "valor": 45},
    ]})
    assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 45


def test_tabela_quebrada_vale_o_default():
    fake = _FakeSupabase(tabelas_quebradas={"followup_joao_ajustes"})
    assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 30


def test_valor_invalido_vale_o_default():
    for valor in (0, -3, "abc", None):
        fake = _FakeSupabase(rows={"followup_joao_ajustes": [
            {"chave": "dias_sem_prospeccao_apos_venda", "valor": valor}]})
        assert S.carregar_dias_sem_prospeccao_apos_venda(fake) == 30, valor


def test_o_contrato_da_tela_de_ajustes_nao_muda():
    assert set(S.AJUSTES_PADRAO) == {"teto_diario_disparos", "adiamento_estoque_dias"}
    assert S.AJUSTE_DIAS_SEM_PROSPECCAO == "dias_sem_prospeccao_apos_venda"

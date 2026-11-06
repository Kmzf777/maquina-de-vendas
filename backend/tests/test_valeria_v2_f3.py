"""F3 (06/11/2026) no runner v2: perguntas antes da vitrine, desqualificação com
motivo e nó, motivo do repasse no contexto dos efeitos e a marcação de sumidos."""
from unittest.mock import MagicMock

import pytest

from app.button_flow import effects
from app.button_flow import valeria_registry_v2 as r2
from app.button_flow import valeria_repasse as varredura
from app.button_flow import valeria_runner_v2 as v2
from app.button_flow.valeria_engine_v2 import DecisaoV2
from app.leads import repasse

from tests.test_valeria_v2_runner import PRONTA_ATACADO, _no, turno  # noqa: F401


@pytest.fixture
def f3(turno, monkeypatch):  # noqa: F811
    desq, codigos = [], []
    monkeypatch.setattr(v2._qualificado, "registrar_desqualificado",
                        lambda **kw: desq.append(kw) or True)

    def _aplicar(efeitos, **kw):
        # O código do motivo precisa estar no contexto DENTRO dos efeitos (é lá que
        # effects.py chama registrar_repasse).
        codigos.append(repasse._motivo_do_turno.get())
        turno.registro["efeitos"].append(efeitos)
        turno.registro["kw_efeitos"].append(kw)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)
    turno.desq, turno.codigos = desq, codigos
    return turno


@pytest.mark.asyncio
async def test_anuncio_de_atacado_pergunta_antes_e_so_depois_mostra_a_vitrine(f3):
    t = f3
    estado = await t(PRONTA_ATACADO)
    assert t.provedor.tipos() == ["botoes"]
    assert t.provedor.chamadas[0][1] == r2.NOS["QA_USO"].corpo
    assert "R$" not in t.provedor.chamadas[0][1]
    assert estado["node"] == "QA_USO" and estado["ramo"] == "atacado"

    await t("Pra revender", payload="revender", titulo="Pra revender")
    await t("30 a 100 kg", payload="ate100", titulo="30 a 100 kg")
    assert all(c[0] == "botoes" for c in t.provedor.chamadas), "nenhuma tabela ainda"
    estado = await t("Sou MEI", payload="mei", titulo="Sou MEI")
    assert t.provedor.tipos()[-3:] == ["carrossel", "texto", "botoes"]
    assert estado["node"] == "VA" and estado["viu"] == ["vitrine", "tabela"]
    assert estado["respostas"] == {"QA_USO": "revender", "QA_VOL": "ate100", "QA_CNPJ": "mei"}

    await t("Fazer pedido", payload="pedido", titulo="Fazer pedido")
    estado = await t("Loja ou empório", payload="loja", titulo="Loja ou empório")
    assert estado["node"] == "T_HANDOFF", "volume já respondido: sem QA2"
    assert t.codigos[-1] == "fim_dos_botoes"
    nota = t.registro["notas"][-1]
    assert "Uso: Pra revender · Volume: 30 a 100 kg/mês · CNPJ: Sou MEI" in nota
    assert t.desq == []


@pytest.mark.asyncio
async def test_sem_cnpj_vai_a_loja_com_tag_e_grava_desqualificacao(f3):
    t = f3
    t.conversa["flow_state"] = _no(None, "QA_CNPJ", ramo="atacado",
                                   respostas={"QA_USO": "revender", "QA_VOL": "ate30"})
    estado = await t("Não tenho CNPJ", payload="sem_cnpj", titulo="Não tenho CNPJ")
    assert estado["node"] == "T_SEM_CNPJ"
    assert t.provedor.tipos() == ["texto"]
    assert "ESPECIAL10" in t.provedor.chamadas[0][1]
    ef = t.registro["efeitos"][-1]
    assert ef.handoff is False and ef.tags == ("Atacado sem CNPJ",)
    assert t.desq == [{"lead_id": "L1", "motivo": "sem_cnpj", "no": "QA_CNPJ",
                       "source": "button_flow", "conversation_id": "C1", "ramo": "atacado",
                       "chave": "QA_CNPJ"}]
    assert estado["desqualificado"]["motivo"] == "sem_cnpj"
    assert estado["desqualificado"]["no"] == "QA_CNPJ"


@pytest.mark.asyncio
async def test_consumo_proprio_vai_a_loja_e_grava_consumidor_final(f3):
    t = f3
    await t(PRONTA_ATACADO)
    estado = await t("Consumo próprio", payload="consumo", titulo="Consumo próprio")
    assert estado["node"] == "C1" and estado["ramo"] == "consumo"
    assert t.desq[0]["motivo"] == "consumidor_final" and t.desq[0]["no"] == "QA_USO"
    assert t.registro["efeitos"][-1].handoff is False
    # Volta a pedir quantidade: deixa de estar desqualificado e vai ao volume.
    estado = await t("Quero em quantidade", payload="quantidade", titulo="Quero em quantidade")
    assert estado["node"] == "QA_VOL" and "desqualificado" not in estado
    assert estado["ramo"] == "atacado"


@pytest.mark.asyncio
async def test_kit_amostra_leva_o_codigo_kit(f3):
    t = f3
    t.conversa["flow_state"] = _no(None, "VK", ramo="atacado")
    await t("Quero o kit", payload="quero_kit", titulo="Quero o kit")
    assert t.codigos[-1] == "kit_amostra"


@pytest.mark.asyncio
async def test_clique_sem_repasse_nao_poe_codigo(f3):
    await f3(PRONTA_ATACADO)
    assert f3.codigos == [None]


@pytest.mark.parametrize("destino,motivo,codigo", [
    ("T_KIT", 'clicou "Quero o kit"', "kit_amostra"),
    ("T_HANDOFF", 'clicou "Cafeteria"', "fim_dos_botoes"),
    ("T_HANDOFF", 'clicou "Falar com vendedor"', "pediu_vendedor"),
    ("T_HANDOFF", "PERGUNTA: emite nota?", "pediu_vendedor"),
    ("T_HANDOFF", "sem resposta a botões (2 mensagens não entendidas)", "ruido"),
    ("T_HANDOFF", "automático — parado há 4h em QA1", "automatico"),
])
def test_codigo_do_repasse(destino, motivo, codigo):
    assert v2.codigo_do_repasse(DecisaoV2(proximo_no=destino, repasse_motivo=motivo)) == codigo


@pytest.mark.parametrize("estado,motivo", [
    ({"viu": ["vitrine", "tabela"]}, "sumiu_depois_da_tabela"),
    ({"viu": ["vitrine"]}, "sumiu_antes_da_tabela"),
    ({}, "sumiu_antes_da_tabela"),
    (None, "sumiu_antes_da_tabela"),
])
def test_motivo_de_sumico(estado, motivo):
    assert v2.motivo_de_sumico(estado) == motivo


@pytest.mark.asyncio
async def test_marcar_sumido_grava_o_no_onde_parou(monkeypatch):
    desq = []
    monkeypatch.setattr(v2._qualificado, "registrar_desqualificado",
                        lambda **kw: desq.append(kw) or True)
    travas = []
    monkeypatch.setattr(v2, "_travar_sumico", lambda *a: travas.append(a) or True)
    conv = {"id": "C1", "last_customer_message_at": "2026-11-04T10:00:00+00:00",
            "flow_state": _no(None, "QA_VOL", ramo="atacado")}
    assert await v2.marcar_sumido(lead={"id": "L1"}, conversation=conv) == "sumiu_antes_da_tabela"
    assert desq[0]["no"] == "QA_VOL" and desq[0]["ramo"] == "atacado"
    assert desq[0]["chave"] == "2026-11-04T10:00:00+00:00"
    assert travas[0][2] == "QA_VOL"


@pytest.mark.asyncio
@pytest.mark.parametrize("node", ["T_HANDOFF", "T_SEM_CNPJ", "T_OPTOUT"])
async def test_marcar_sumido_ignora_terminal(monkeypatch, node):
    monkeypatch.setattr(v2, "_travar_sumico", MagicMock(side_effect=AssertionError))
    conv = {"id": "C1", "flow_state": _no(None, node)}
    assert await v2.marcar_sumido(lead={"id": "L1"}, conversation=conv) is None


@pytest.mark.asyncio
async def test_marcar_sumido_perde_a_trava_nao_grava(monkeypatch):
    desq = []
    monkeypatch.setattr(v2._qualificado, "registrar_desqualificado",
                        lambda **kw: desq.append(kw))
    monkeypatch.setattr(v2, "_travar_sumico", lambda *a: False)
    conv = {"id": "C1", "flow_state": _no(None, "VA", ramo="atacado", viu=["vitrine", "tabela"])}
    assert await v2.marcar_sumido(lead={"id": "L1"}, conversation=conv) is None
    assert desq == []


@pytest.mark.asyncio
async def test_varredura_de_sumidos_pula_humano_e_respeita_a_flag(monkeypatch):
    linhas = [
        {"id": "C1", "flow_state": {}, "leads": {"id": "L1", "human_control": False}},
        {"id": "C2", "flow_state": {}, "leads": {"id": "L2", "human_control": True}},
        {"id": "C3", "flow_state": {}, "leads": [{"id": "L3", "opt_out": True}]},
    ]
    monkeypatch.setattr(varredura, "get_supabase", lambda: object())
    monkeypatch.setattr(varredura, "_pagina_sumidos", lambda *a: linhas)
    chamados = []

    async def _marcar(*, lead, conversation):
        chamados.append(lead["id"])
        return "sumiu_antes_da_tabela"
    monkeypatch.setattr(v2, "marcar_sumido", _marcar)
    assert await varredura.marcar_sumidos() == 1
    assert chamados == ["L1"]
    monkeypatch.setenv("VALERIA_DESQUALIFICA_SUMIDOS_ENABLED", "off")
    assert await varredura.marcar_sumidos() == 0


@pytest.mark.asyncio
async def test_varrer_marca_sumidos_mesmo_com_repasse_auto_desligado(monkeypatch):
    monkeypatch.delenv("VALERIA_REPASSE_AUTO_ENABLED", raising=False)
    chamado = []

    async def _sumidos():
        chamado.append(1)
        return 0
    monkeypatch.setattr(varredura, "marcar_sumidos", _sumidos)
    assert await varredura.varrer() == 0
    assert chamado == [1]

"""F3 na v1 dos botões (a que roda em produção; perfil do número da Valéria, 11/11/2026).

- Pergunta de CNPJ (NC) entre o volume (N2) e o fornecedor (N3); sem CNPJ vai à loja.
- Desqualificação com motivo e nó (consumidor final, sem CNPJ).
- Motivo do repasse no contexto dos efeitos (fim dos botões, pediu vendedor, ruído).
- Fim da "Valéria muda": terminal sem repasse reabre quando o lead pede contato.
- Sumidos da v1: antes ou depois do preço, pelo nó.
"""
import pytest

from app.button_flow import effects
from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as runner
from app.button_flow import valeria_runner_v2 as v2
from app.leads import repasse

from tests.test_valeria_encerramento_2026_09_30 import turno  # noqa: F401 — fixture


@pytest.fixture
def v1(turno, monkeypatch):  # noqa: F811
    desq, codigos = [], []

    def _aplicar(efeitos, **_kw):
        codigos.append(repasse._motivo_do_turno.get())
        turno.registro["efeitos"].append(efeitos)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)
    import app.leads.qualificado as q
    monkeypatch.setattr(q, "registrar_desqualificado", lambda **kw: desq.append(kw) or True)
    turno.desq, turno.codigos = desq, codigos
    return turno


def test_nc_entre_volume_e_fornecedor():
    assert {b.destino for b in reg.NOS["N2"].botoes} == {"NC"}
    assert {b.id: b.destino for b in reg.NOS["NC"].botoes} == {
        "cnpj": "N3", "mei": "N3", "sem_cnpj": "T_SEM_CNPJ"}
    assert reg.NOS["NC"].ramo == "atacado"
    assert all(len(b.rotulo) <= reg.LIMITE_ROTULO_BOTAO for b in reg.NOS["NC"].botoes)
    t = reg.TERMINAIS["T_SEM_CNPJ"]
    assert t.handoff is False and t.tags == (reg.TAG_SEM_CNPJ,)


@pytest.mark.asyncio
async def test_ramo_atacado_com_cnpj_chega_ao_joao_com_motivo(v1):
    t = v1
    await t("Pro meu negócio", payload="negocio", no="N0")
    await t("Cafeteria", payload="cafeteria")
    estado = await t("30 a 100 kg", payload="ate100")
    assert estado["node"] == "NC" and estado["ramo"] == "atacado"
    estado = await t("Sou MEI", payload="mei")
    assert estado["node"] == "N3"
    await t("Quero trocar", payload="trocar")
    await t("Próximos 15 dias", payload="dias15")
    estado = await t("Sim, quero falar", payload="sim")
    assert estado["node"] == "T_HANDOFF"
    assert t.codigos[-1] == "fim_dos_botoes"
    assert t.desq == []


@pytest.mark.asyncio
async def test_sem_cnpj_vai_a_loja_sem_repasse_e_grava_desqualificacao(v1):
    t = v1
    t.conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": "NC", "nudges": 0,
                                "ramo": "atacado"}
    estado = await t("Não tenho CNPJ", payload="sem_cnpj")
    assert estado["node"] == "T_SEM_CNPJ"
    assert t.registro["efeitos"][-1].handoff is False
    assert t.registro["efeitos"][-1].tags == ("Atacado sem CNPJ",)
    assert t.desq[0]["motivo"] == "sem_cnpj" and t.desq[0]["no"] == "NC"
    assert estado["desqualificado"]["motivo"] == "sem_cnpj"


@pytest.mark.asyncio
async def test_consumo_vai_a_loja_e_grava_consumidor_final(v1):
    estado = await v1("Pra consumo próprio", payload="consumo", no="N0")
    assert estado["node"] == "C1"
    assert v1.desq[0]["motivo"] == "consumidor_final" and v1.desq[0]["no"] == "N0"


@pytest.mark.asyncio
async def test_duvida_na_loja_vai_ao_joao(v1):
    estado = await v1("Tenho uma dúvida", payload="duvida", no="C1")
    assert estado["node"] == "T_HANDOFF"
    assert v1.registro["efeitos"][-1].handoff is True
    assert v1.codigos[-1] == "pediu_vendedor"


@pytest.mark.asyncio
async def test_quarto_texto_vai_ao_vendedor_do_ramo(v1):
    v1.conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": "P2", "nudges": reg.TETO_NUDGES}
    estado = await v1("quero 300 pacotes com a minha logo")
    assert estado["node"] == "T_HANDOFF_PL"
    assert v1.codigos[-1] == "ruido"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", sorted(reg.TERMINAIS_QUE_REABREM))
async def test_quem_volta_perguntando_e_atendido(v1, terminal):
    estado = await v1("Como faço pra comprar", no=terminal)
    assert estado["node"] == "T_HANDOFF"
    assert v1.registro["efeitos"][-1].handoff is True
    assert v1.codigos[-1] == "pediu_vendedor"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", sorted(reg.TERMINAIS_QUE_REABREM))
async def test_quem_volta_agradecendo_segue_ignorado(v1, terminal):
    estado = await v1("obrigado", no=terminal)
    assert estado["node"] == terminal
    assert v1.registro["efeitos"] == []


@pytest.mark.asyncio
async def test_sim_quero_falar_depois_do_adiamento(v1):
    """Tel. final 5468."""
    v1.conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": "T_ADIADO", "nudges": 0,
                                 "ramo": "atacado"}
    estado = await v1("Sim, quero falar", payload="sim", titulo="Sim, quero falar")
    assert estado["node"].startswith("T_HANDOFF")
    assert v1.registro["efeitos"][-1].handoff is True


@pytest.mark.parametrize("node,motivo", [
    ("N2", "sumiu_antes_da_tabela"), ("NC", "sumiu_antes_da_tabela"),
    ("N5", "sumiu_depois_da_tabela"), ("P4", "sumiu_depois_da_tabela"),
])
def test_sumico_da_v1_pelo_no(node, motivo):
    assert v2.motivo_de_sumico({"flow": reg.FLOW_ID, "node": node}) == motivo


@pytest.mark.asyncio
async def test_marcar_sumido_da_v1(monkeypatch):
    desq = []
    monkeypatch.setattr(v2._qualificado, "registrar_desqualificado",
                        lambda **kw: desq.append(kw) or True)
    monkeypatch.setattr(v2, "_travar_sumico", lambda *a: True)
    conv = {"id": "C1", "flow_state": {"flow": reg.FLOW_ID, "node": "N5", "nudges": 0}}
    assert await v2.marcar_sumido(lead={"id": "L1"}, conversation=conv) == "sumiu_depois_da_tabela"
    assert desq[0]["no"] == "N5" and desq[0]["ramo"] == "atacado"


def test_estado_da_v1_guarda_o_ramo_e_limpa_a_desqualificacao():
    campos = runner.proximo_estado({"flow": reg.FLOW_ID, "node": "C1",
                                    "desqualificado": {"motivo": "consumidor_final"}}, "N1")
    assert campos["ramo"] == "atacado" and "desqualificado" not in campos

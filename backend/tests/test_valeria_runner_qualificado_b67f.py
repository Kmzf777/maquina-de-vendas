"""`valeria_runner.aplicar_criterios` (cartão b67f1c6b, B4).

- O score só é gravado para lead B2B (D9): segmento atacado/private_label ou `fn_lead_b2b`.
  Deixa de depender de `stage='atacado'`; ter score não torna ninguém B2B.
- Quando o score fecha `final_score >= 5` definitivo, grava o evento `qualificado`
  (criterio='score', source='score', b2b=True).
"""
import pytest

from app.button_flow import valeria_runner as runner


@pytest.fixture
def dubles(monkeypatch):
    estado = {"gravados": [], "qualificados": [], "b2b_rpc": [], "b2b": False,
              "snapshot": {"final_score": 3, "is_provisional": True}, "lead_db": None}

    def salvar(**kw):
        estado["gravados"].append(kw)
        return estado["snapshot"]

    def b2b(lead_id):
        estado["b2b_rpc"].append(lead_id)
        return estado["b2b"]

    monkeypatch.setattr(runner, "save_score_evidence", salvar)
    monkeypatch.setattr(runner, "lead_e_b2b", b2b)
    monkeypatch.setattr(runner, "registrar_qualificado",
                        lambda **kw: estado["qualificados"].append(kw) or True)
    monkeypatch.setattr(runner, "_ler_lead_para_score", lambda lead_id: estado["lead_db"])
    return estado


@pytest.mark.asyncio
@pytest.mark.parametrize("lead", [
    {"id": "l1", "segmento": "atacado", "stage": "qualificando"},
    {"id": "l1", "segmento": "private_label", "stage": "qualificando"},
    {"id": "l1", "segmento": None, "stage": "atacado"},          # antes do backfill F2
    {"id": "l1", "stage": "Private Label"},                       # select antigo, sem a coluna
])
async def test_segmento_b2b_grava_sem_rpc(dubles, lead):
    await runner.aplicar_criterios("l1", {"segment": "cafeteria"}, lead=lead)
    assert len(dubles["gravados"]) == 1
    assert dubles["b2b_rpc"] == [], "segmento B2B já basta; não chama fn_lead_b2b"


@pytest.mark.asyncio
async def test_lead_pending_nao_b2b_nao_grava(dubles):
    dubles["b2b"] = False
    await runner.aplicar_criterios("l1", {"segment": "cafeteria"},
                                   lead={"id": "l1", "segmento": None, "stage": "pending"})
    assert dubles["gravados"] == []
    assert dubles["b2b_rpc"] == ["l1"]
    assert dubles["qualificados"] == []


@pytest.mark.asyncio
async def test_consumo_nao_grava(dubles):
    dubles["b2b"] = False
    await runner.aplicar_criterios("l1", {"segment": "cafeteria"},
                                   lead={"id": "l1", "segmento": "consumo", "stage": "qualificando"})
    assert dubles["gravados"] == []


@pytest.mark.asyncio
async def test_lead_sem_segmento_mas_b2b_pelo_banco_grava(dubles):
    """CNPJ no Bling ou deal em funil Atacado/PL: fn_lead_b2b decide."""
    dubles["b2b"] = True
    await runner.aplicar_criterios("l1", {"segment": "cafeteria"},
                                   lead={"id": "l1", "segmento": None, "stage": "triagem"})
    assert len(dubles["gravados"]) == 1
    assert dubles["b2b_rpc"] == ["l1"]


@pytest.mark.asyncio
async def test_sem_lead_le_do_banco(dubles):
    """Chamador antigo (valeria_runner_v2) não passa o lead: o runner lê segmento/stage."""
    dubles["lead_db"] = {"id": "l1", "segmento": "atacado", "stage": "qualificando"}
    await runner.aplicar_criterios("l1", {"segment": "cafeteria"})
    assert len(dubles["gravados"]) == 1
    assert dubles["b2b_rpc"] == []


@pytest.mark.asyncio
async def test_score_definitivo_5_registra_qualificado(dubles):
    dubles["snapshot"] = {"final_score": 5, "is_provisional": False}
    await runner.aplicar_criterios("l1", {"purchase_intent": "clear"},
                                   lead={"id": "l1", "segmento": "private_label"})
    assert dubles["qualificados"] == [{
        "lead_id": "l1", "criterio": "score", "source": "score", "b2b": True,
        "segmento": "private_label",
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [
    {"final_score": 10, "is_provisional": True},    # provisório não conta
    {"final_score": 4, "is_provisional": False},    # abaixo de 5
    None,                                           # dublê/erro sem snapshot
])
async def test_score_que_nao_fecha_nao_registra(dubles, snapshot):
    dubles["snapshot"] = snapshot
    await runner.aplicar_criterios("l1", {"purchase_intent": "clear"},
                                   lead={"id": "l1", "segmento": "atacado"})
    assert dubles["qualificados"] == []


@pytest.mark.asyncio
async def test_falha_ao_registrar_qualificado_nao_derruba(dubles, monkeypatch):
    dubles["snapshot"] = {"final_score": 6, "is_provisional": False}

    def explode(**_kw):
        raise RuntimeError("lead_events fora")
    monkeypatch.setattr(runner, "registrar_qualificado", explode)
    await runner.aplicar_criterios("l1", {"purchase_intent": "clear"},
                                   lead={"id": "l1", "segmento": "atacado"})
    assert len(dubles["gravados"]) == 1

"""F3 (06/11/2026): um lead NOVO do anúncio de Atacado ganha score.

O lead chega pela mensagem pronta, sem `segmento` (só o repasse define), e toca os
botões do ramo de atacado. Antes da correção, `aplicar_criterios` recusava o score
("não é B2B (segmento=None)") porque só olhava o segmento gravado no lead.
"""
import pytest

from app.button_flow import valeria_runner as v1
from app.leads import segmento as seg_mod

from tests.test_valeria_v2_runner import PRONTA_ATACADO, turno  # noqa: F401 — fixture


@pytest.fixture
def lead_novo(turno, monkeypatch):  # noqa: F811
    turno.lead["segmento"] = None
    turno.lead["stage"] = "pending"
    chamadas = []
    monkeypatch.setattr(v1, "lead_e_b2b", lambda lid: chamadas.append(lid) or False)
    turno.rpc = chamadas
    return turno


@pytest.mark.asyncio
async def test_lead_novo_do_anuncio_de_atacado_ganha_score(lead_novo):
    t = lead_novo
    await t("Olá! Tenho um comércio e quero revender café especial.")
    # Toca um card da vitrine ("Quero esse") e depois o tipo de negócio.
    await t("Quero esse", payload="card:classico", titulo="Quero esse")
    await t("Cafeteria", payload="cafeteria", titulo="Cafeteria")
    gravados = [g["updates"] for g in t.registro["score"]]
    assert {"purchase_intent": "clear"} in gravados
    assert {"segment": "cafeteria"} in gravados
    assert t.rpc == [], "o ramo do clique decide; fn_lead_b2b nem é chamada"


@pytest.mark.asyncio
async def test_lead_novo_no_ramo_consumo_nao_ganha_score(lead_novo):
    # Nenhum nó de consumo declara `grava`; o portão também barra pelo ramo.
    await v1.aplicar_criterios("L1", {"segment": "cafeteria"}, ramo="consumo",
                               lead=lead_novo.lead)
    assert lead_novo.registro["score"] == []
    assert seg_mod.SEGMENTOS_B2B == ("atacado", "private_label")

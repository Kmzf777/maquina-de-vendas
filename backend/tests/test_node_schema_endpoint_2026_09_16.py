"""Contrato do endpoint GET /api/campaigns/node-schema.

O inspector do builder (/campanhas) mantinha uma copia hard-coded dos campos de
cada tipo de no — foi essa copia que gravava rotulo de coluna onde o motor lia
segmento de lead (ver `app/campaigns/node_registry.py`, cabecalho). Este endpoint
e o proximo passo do plano: a tela para de ter opiniao propria e passa a renderizar
a partir do REGISTRO. Estes testes fixam o contrato HTTP desse endpoint, nao o
conteudo do registro em si (isso ja e coberto por `test_node_registry.py`).

Dois riscos concretos que os testes abaixo existem para pegar:
1. Ordem de rota no FastAPI: `/{campaign_id}` ja existe no router. Se `/node-schema`
   for declarada DEPOIS dela, "node-schema" casa como campaign_id e o endpoint novo
   nunca e alcancado.
2. `para_json()`/`VALORES_FIXOS` vazando algo que o `json` puro nao serializa (set,
   por exemplo) na fronteira do endpoint.
"""
import asyncio
import json

from fastapi.testclient import TestClient

from app.main import app
from app.campaigns.node_registry import REGISTRO, VOCABULARIOS, VALORES_FIXOS

client = TestClient(app)

_ENDPOINT = "/api/campaigns/node-schema"

_CHAVES_TIPO = {"tipo", "subtipo", "rotulo", "icone", "na_paleta", "requer_um_de", "campos"}
_CHAVES_CAMPO = {"chave", "vocab", "rotulo", "obrigatorio", "default", "ajuda"}


def test_endpoint_responde_200():
    r = client.get(_ENDPOINT)
    assert r.status_code == 200


def test_rota_estatica_vence_a_parametrizada_campaign_id():
    """Prova da armadilha do plano: se /node-schema viesse depois de /{campaign_id}
    no router, este GET cairia em `api_get_campaign("node-schema")` — 404 (campaign
    nao encontrada) ou erro de UUID, nunca o schema. 200 + chave "tipos" so acontece
    se a rota estatica foi declarada ANTES da parametrizada."""
    r = client.get(_ENDPOINT)
    assert r.status_code == 200
    body = r.json()
    assert "tipos" in body
    assert isinstance(body["tipos"], list)


def test_resposta_tem_uma_entrada_por_item_do_registro():
    body = client.get(_ENDPOINT).json()
    assert len(body["tipos"]) == len(REGISTRO)
    assert len(body["tipos"]) > 0  # sanidade: REGISTRO nao esta vazio


def test_cada_entrada_traz_exatamente_as_chaves_esperadas():
    body = client.get(_ENDPOINT).json()
    for entrada in body["tipos"]:
        assert set(entrada.keys()) == _CHAVES_TIPO, entrada


def test_cada_campo_traz_exatamente_as_chaves_esperadas():
    body = client.get(_ENDPOINT).json()
    achou_algum_campo = False
    for entrada in body["tipos"]:
        for campo in entrada["campos"]:
            achou_algum_campo = True
            assert set(campo.keys()) == _CHAVES_CAMPO, campo
    assert achou_algum_campo, "nenhum campo no payload inteiro — fixture nao prova nada"


def test_todo_vocab_devolvido_esta_em_vocabularios():
    body = client.get(_ENDPOINT).json()
    usados = {campo["vocab"] for entrada in body["tipos"] for campo in entrada["campos"]}
    assert usados, "nenhum vocab encontrado no payload"
    assert usados <= VOCABULARIOS, usados - VOCABULARIOS


def test_payload_cru_do_endpoint_e_json_puro_sem_tupla_dataclass_ou_set():
    """Chama a coroutine do endpoint DIRETO, sem passar pelo jsonable_encoder do
    FastAPI — ele converteria set/tupla/dataclass por baixo dos panos e esconderia
    o bug no round-trip HTTP. json.dumps sobre o retorno cru nao pode levantar."""
    from app.campaigns import router as campaigns_router

    resposta = asyncio.run(campaigns_router.api_node_schema())
    json.dumps(resposta)  # TypeError aqui = set/dataclass vazou na fronteira


def test_regressao_stage_filter_stage_stagnation_e_segmento_lead_deal_stage_enter_e_etapa_key():
    """O bug que motivou node_registry.py inteiro: `stage_filter` e o MESMO nome de
    chave em dois gatilhos com vocabularios opostos (leads.stage vs
    pipeline_stages.key). E por isso que este endpoint existe — para a tela
    descobrir a diferenca em vez de usar um unico <select> para os dois."""
    body = client.get(_ENDPOINT).json()

    def campo_stage_filter(tipo, subtipo):
        entrada = next(e for e in body["tipos"] if e["tipo"] == tipo and e["subtipo"] == subtipo)
        return next(c for c in entrada["campos"] if c["chave"] == "stage_filter")

    assert campo_stage_filter("trigger", "stage_stagnation")["vocab"] == "segmento_lead"
    assert campo_stage_filter("trigger", "deal_stage_enter")["vocab"] == "etapa_key"


def test_valores_fixos_sao_expostos_para_os_selects_de_enum_fechado():
    """node_registry expoe VALORES_FIXOS (vocabularios fechados que nao vem do
    banco: segmento_lead, operador, politica_resposta, severidade, falante). O
    endpoint devolve para a tela montar os <select> sem re-hardcodar a lista."""
    body = client.get(_ENDPOINT).json()
    assert "valores_fixos" in body
    esperado = {
        chave: [list(par) for par in valores]
        for chave, valores in VALORES_FIXOS.items()
    }
    assert body["valores_fixos"] == esperado
    # sanidade: todo vocab fechado usado por algum campo tem entrada em valores_fixos
    vocabs_fechados_em_uso = {
        campo["vocab"]
        for entrada in body["tipos"]
        for campo in entrada["campos"]
        if campo["vocab"] in VALORES_FIXOS
    }
    assert vocabs_fechados_em_uso <= set(body["valores_fixos"].keys())

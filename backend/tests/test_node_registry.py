"""Contrato do registro de nos do builder de cadencias (/campanhas).

Estes testes NAO exercitam comportamento: eles amarram o REGISTRO ao que o motor
(`app/automation/engine.py` + `triggers.py`) de fato le do `config` de cada no. O
builder e o motor divergiram em silencio por toda a vida do produto — 16 campanhas,
0 ativas, 0 matriculas na historia — porque nada no repositorio cruzava as duas
pontas. O teste `test_toda_chave_lida_pelo_motor_esta_no_registro` e esse cruzamento:
qualquer `cfg.get("...")` novo no motor quebra a suite ate ser declarado.
"""
import re, io, pathlib
from app.campaigns.node_registry import REGISTRO, VOCABULARIOS

RAIZ = pathlib.Path(__file__).resolve().parents[1] / "app" / "automation"

def _chaves_lidas(arquivo: str) -> set[str]:
    txt = io.open(RAIZ / arquivo, encoding="utf-8").read()
    return set(re.findall(r'cfg\.get\(\s*"([a-z_]+)"', txt))

def test_toda_chave_lida_pelo_motor_esta_no_registro():
    declaradas = {c.chave for t in REGISTRO.values() for c in t.campos}
    internas = {"trigger_type", "action_type", "condition_type", "final_actions",
                "stage_name", "limit"}
    lidas = _chaves_lidas("engine.py") | _chaves_lidas("triggers.py")
    faltando = lidas - declaradas - internas
    assert not faltando, f"motor le chaves fora do registro: {sorted(faltando)}"

def test_vocabulario_de_stage_filter_por_gatilho():
    esperado = {
        "no_message": "segmento_lead", "stage_stagnation": "segmento_lead",
        "no_sale_in_stage": "segmento_lead", "stage_enter": "segmento_lead",
        "deal_stage_enter": "etapa_key",
    }
    for sub, vocab in esperado.items():
        campo = next(c for c in REGISTRO[("trigger", sub)].campos if c.chave == "stage_filter")
        assert campo.vocab == vocab, f"{sub}: {campo.vocab} != {vocab}"

def test_stage_filter_obrigatorio_onde_o_motor_pula_sem_ele():
    for sub in ("stage_stagnation", "no_sale_in_stage"):
        campo = next(c for c in REGISTRO[("trigger", sub)].campos if c.chave == "stage_filter")
        assert campo.obrigatorio, f"{sub}: stage_filter tem de ser obrigatorio"

def test_create_deal_exige_funil():
    campos = {c.chave: c for c in REGISTRO[("action", "create_deal")].campos}
    assert campos["pipeline_id"].vocab == "funil_id"
    assert campos["pipeline_id"].obrigatorio
    assert "stage_key" in campos and campos["stage_key"].vocab == "etapa_key"

def test_send_exige_template():
    campo = next(c for c in REGISTRO[("send", None)].campos if c.chave == "template_name")
    assert campo.vocab == "template" and campo.obrigatorio

def test_deal_stage_stagnation_requer_etapa_por_id_ou_key():
    assert ("stage_id", "stage_key") in REGISTRO[("trigger", "deal_stage_stagnation")].requer_um_de

def test_on_reply_existe_no_gatilho_e_nao_tem_default_no_no():
    gat = {c.chave: c for c in REGISTRO[("trigger", "deal_stage_stagnation")].campos}
    assert gat["on_reply"].vocab == "politica_resposta"
    envio = {c.chave: c for c in REGISTRO[("send", None)].campos}
    assert envio["on_reply"].default is None

def test_replied_only_nao_existe():
    campos = {c.chave for c in REGISTRO[("trigger", "post_broadcast")].campos}
    assert "replied_only" not in campos

def test_todo_vocabulario_usado_e_conhecido():
    for t in REGISTRO.values():
        for c in t.campos:
            assert c.vocab in VOCABULARIOS, f"{t.subtipo}.{c.chave}: {c.vocab}"

def test_as_nove_condicoes_estao_na_paleta():
    conds = [t for (tipo, _), t in REGISTRO.items() if tipo == "condition"]
    assert len(conds) == 9
    assert all(t.na_paleta for t in conds)


def test_para_json_devolve_o_contrato_serializavel():
    """`para_json()` e o que a TELA vai consumir (Task 2) — entao tem de atravessar
    `json.dumps` sem `default=`: nada de dataclass, tupla aninhada em chave, ou
    `datetime`. O formato e fechado de proposito (comparacao por igualdade, nao
    `issubset`): campo novo no registro que a tela nao saiba renderizar tem de
    quebrar aqui, e nao virar controle invisivel no inspector."""
    import json
    from app.campaigns.node_registry import para_json

    dados = para_json()
    assert isinstance(dados, list) and len(dados) == len(REGISTRO)
    json.dumps(dados)  # sem default= : tem de ser JSON puro

    for t in dados:
        assert set(t) == {"tipo", "subtipo", "rotulo", "icone", "na_paleta",
                          "requer_um_de", "campos"}, f"chaves do no: {sorted(t)}"
        assert isinstance(t["campos"], list)
        assert isinstance(t["requer_um_de"], list)
        for grupo in t["requer_um_de"]:
            assert isinstance(grupo, list) and len(grupo) >= 2
        for c in t["campos"]:
            assert set(c) == {"chave", "vocab", "rotulo", "obrigatorio", "default",
                              "ajuda"}, f"chaves do campo: {sorted(c)}"
            assert isinstance(c["obrigatorio"], bool)
            assert isinstance(c["chave"], str) and c["chave"]
            assert isinstance(c["rotulo"], str) and c["rotulo"]

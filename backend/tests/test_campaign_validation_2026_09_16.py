"""Validacao de ativacao do builder de campanhas (/campanhas) — uma prova por regra.

Cada teste INJETA uma violacao num grafo que, fora ela, e valido, e exige que a
validacao acuse exatamente aquela regra. O grafo bom que devolve `[]` e o ULTIMO teste
do arquivo de proposito: sozinho ele passaria ate com `def validar(...): return []`.

O grafo-base (`_grafo`) e uma cadencia real — gatilho de card parado, toque 1, espera,
"respondeu?" e toque 2 — e tem um LOSANGO (os dois ramos da condicao desaguam no mesmo
`fim`). O losango nao e enfeite: e o caso que separa a deteccao de ciclo de verdade
(cinza/preto) de um "ja visitei este no" ingenuo, que acusaria ciclo onde nao ha. Por
isso `test_ciclo` tambem afirma que o grafo-base NAO tem ciclo.
"""
import pytest

from app.campaigns.validation import Problema, validar

FUNIL = "11111111-1111-4111-8111-111111111111"
ETAPA = "22222222-2222-4222-8222-222222222222"
CANAL = "33333333-3333-4333-8333-333333333333"

T1 = "joao_conversa_atacado_t1"
T2 = "joao_conversa_atacado_t2"
# nome -> status CRU da Meta, como `message_templates.status` guarda.
TEMPLATES = {T1: "APPROVED", T2: "APPROVED"}

_GATILHO_OK = {
    "trigger_type": "deal_stage_stagnation",
    "stage_id": ETAPA,
    "pipeline_id": FUNIL,
    "stage_days": 15,
    "silence_days": 0,
    "last_speaker": "qualquer",
    "limit": 20,
    "on_reply": "cancel",
}


def _no(nid, tipo, config=None, *, prox=None, sim=None, nao=None):
    """Uma linha de `campaign_nodes` como o PostgREST devolve."""
    return {
        "id": nid, "campaign_id": "camp", "type": tipo, "config": dict(config or {}),
        "next_node_id": prox, "yes_node_id": sim, "no_node_id": nao,
    }


def _grafo():
    """gatilho → toque 1 → espera → "respondeu?"; SIM → fim, NAO → toque 2 → fim."""
    campanha = {"id": "camp", "name": "Reposicao — Joao", "channel_id": CANAL}
    nos = [
        _no("gat", "trigger", _GATILHO_OK, prox="t1"),
        _no("t1", "send", {"template_name": T1, "template_language": "pt_BR"}, prox="esp"),
        _no("esp", "wait", {"days": 3}, prox="cond"),
        _no("cond", "condition", {"condition_type": "replied_recently", "days": 5},
            sim="fim", nao="t2"),
        _no("t2", "send", {"template_name": T2}, prox="fim"),
        _no("fim", "end", {"label": "Encerrar"}),
    ]
    return campanha, nos


def _grafo_de_um_no(tipo, config, *, gatilho_cfg=None):
    """gatilho → <no sob teste> → fim. `prox`/`sim`/`nao` todos apontam para o fim,
    entao o mesmo construtor serve para condicao e para os demais tipos."""
    campanha = {"id": "camp", "name": "Teste", "channel_id": CANAL}
    nos = [
        _no("gat", "trigger", gatilho_cfg or _GATILHO_OK, prox="meio"),
        _no("meio", tipo, config, prox="fim", sim="fim", nao="fim"),
        _no("fim", "end", {}),
    ]
    return campanha, nos


def _por_id(nos, nid):
    return next(n for n in nos if n["id"] == nid)


def _codigos(problemas):
    return sorted(p.codigo for p in problemas)


def _de(problemas, codigo):
    return [p for p in problemas if p.codigo == codigo]


# ── Campos (regras 1 a 4) ────────────────────────────────────────────────────────


def test_campo_obrigatorio_vazio_e_acusado_com_no_id_e_nome_do_campo():
    campanha, nos = _grafo()
    _por_id(nos, "t1")["config"]["template_name"] = ""

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    p = problemas[0]
    assert p.codigo == "campo_obrigatorio"
    assert p.no_id == "t1"
    assert "template_name" in p.mensagem


def test_campo_obrigatorio_ausente_e_acusado_igual_ao_vazio():
    campanha, nos = _grafo()
    del _por_id(nos, "t1")["config"]["template_name"]

    problemas = validar(campanha, nos, TEMPLATES)

    assert _codigos(problemas) == ["campo_obrigatorio"]
    assert problemas[0].no_id == "t1"
    assert "template_name" in problemas[0].mensagem


def test_zero_nao_conta_como_campo_vazio():
    """`0` e `False` sao valores LEGITIMOS. Uma checagem por falsidade (`if not valor`)
    reprovaria 'janela de recompra: 0 dias' e 'pular fim de semana: nao' — a campanha
    nao ativaria e a tela nao teria como mostrar o que esta errado, porque nao esta."""
    campanha, nos = _grafo_de_um_no(
        "wait", {"days": 0, "skip_weekends": False},
        gatilho_cfg={"trigger_type": "repurchase_window", "days": 0})

    assert validar(campanha, nos, TEMPLATES) == []


def test_requer_um_de_nao_satisfeito_e_acusado():
    """`deal_stage_stagnation` sem `stage_id` E sem `stage_key`: a RPC
    get_deals_stage_stagnant e fail-closed com os dois nulos (devolve conjunto vazio),
    entao a esteira liga e nunca acha card nenhum."""
    campanha, nos = _grafo_de_um_no(
        "wait", {"days": 1},
        gatilho_cfg={"trigger_type": "deal_stage_stagnation", "pipeline_id": FUNIL})

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "requer_um_de"
    assert problemas[0].no_id == "gat"
    assert "stage_id" in problemas[0].mensagem and "stage_key" in problemas[0].mensagem


@pytest.mark.parametrize("tipo, config, gatilho_cfg, no_id, valor", [
    # A KEY da etapa no lugar do uuid: `engine._execute_action` le `stage_id` sem
    # nenhum fallback por key — a acao volta sem tocar o card.
    ("action", {"action_type": "move_deal_stage", "stage_id": "fechado_perdido"},
     None, "meio", "fechado_perdido"),
    # O ROTULO do funil no lugar do id — o bug que o node_registry existe para matar.
    ("wait", {"days": 1},
     {"trigger_type": "deal_stage_stagnation", "stage_id": ETAPA,
      "pipeline_id": "Joao - Reposicao"}, "gat", "Joao - Reposicao"),
    # Numero de telefone no lugar do id do canal.
    ("send", {"template_name": T1, "channel_id": "5534988861441"},
     None, "meio", "5534988861441"),
])
def test_vocabulario_de_id_exige_uuid(tipo, config, gatilho_cfg, no_id, valor):
    campanha, nos = _grafo_de_um_no(tipo, config, gatilho_cfg=gatilho_cfg)

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "valor_invalido"
    assert problemas[0].no_id == no_id
    assert valor in problemas[0].mensagem


@pytest.mark.parametrize("vocab, tipo, config, gatilho_cfg, no_id, valor", [
    # engine._compare: operador desconhecido devolve False em TODA comparacao.
    ("operador", "condition",
     {"condition_type": "sale_count", "operator": "maior", "value": 1}, None, "meio", "maior"),
    # worker._apply_reply_policy: valor desconhecido cai em "pausa" e o lead fica
    # inelegivel para sempre (enrollment pausado conta como ativo).
    ("politica_resposta", "send",
     {"template_name": T1, "on_reply": "parar"}, None, "meio", "parar"),
    ("severidade", "action",
     {"action_type": "alert_seller", "severity": "alta", "title": "Esteira encerrada"},
     None, "meio", "alta"),
    # O rotulo da coluna de Kanban onde o motor espera `leads.stage`.
    ("segmento_lead", "action",
     {"action_type": "move_stage", "stage": "Em conversa"}, None, "meio", "Em conversa"),
    # `falante` so aceita qualquer|lead|nos; "vendedor" faz a RPC devolver vazio sempre.
    ("falante", "wait", {"days": 1},
     {"trigger_type": "deal_stage_stagnation", "stage_id": ETAPA,
      "last_speaker": "vendedor"}, "gat", "vendedor"),
])
def test_enum_fechado_recusa_valor_fora_da_lista(vocab, tipo, config, gatilho_cfg, no_id, valor):
    campanha, nos = _grafo_de_um_no(tipo, config, gatilho_cfg=gatilho_cfg)

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, f"{vocab}: {_codigos(problemas)}"
    assert problemas[0].codigo == "valor_invalido"
    assert problemas[0].no_id == no_id
    assert valor in problemas[0].mensagem


# ── Grafo (regras 5 a 10) ────────────────────────────────────────────────────────


def test_campanha_sem_gatilho():
    campanha, nos = _grafo()
    nos = [n for n in nos if n["type"] != "trigger"]

    problemas = validar(campanha, nos, TEMPLATES)

    assert _codigos(problemas) == ["sem_gatilho"]
    assert problemas[0].no_id is None


def test_campanha_com_dois_gatilhos():
    """`triggers.py` e `router` fazem `next(n for n in nodes if n['type']=='trigger')`:
    o segundo gatilho e ignorado em silencio — ele existe na tela e nao dispara nada."""
    campanha, nos = _grafo()
    nos.append(_no("gat2", "trigger", _GATILHO_OK, prox="t1"))

    problemas = validar(campanha, nos, TEMPLATES)

    assert _codigos(problemas) == ["gatilho_duplicado"], (
        "dois gatilhos nao e 'sem gatilho': o conserto e apagar um, nao criar um")
    assert "2" in problemas[0].mensagem


def test_gatilho_sem_proximo_no():
    campanha, nos = _grafo()
    _por_id(nos, "gat")["next_node_id"] = None

    problemas = validar(campanha, nos, TEMPLATES)

    assert _codigos(problemas) == ["gatilho_solto"], (
        "com o gatilho solto a alcancabilidade nao roda: acusar os 5 nos como orfaos "
        "seria enterrar a unica causa real no meio do ruido")
    assert problemas[0].no_id == "gat"


def test_no_inalcancavel_a_partir_do_gatilho():
    campanha, nos = _grafo()
    nos.append(_no("orf", "wait", {"days": 1}, prox="fim"))  # ninguem aponta para ele

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "no_inalcancavel"
    assert problemas[0].no_id == "orf"
    assert "Aguardar" in problemas[0].mensagem, "o no orfao tem de ser NOMEADO"


def test_condicao_sem_ramo_sim():
    """`engine._execute_condition` faz `next = yes if result else no`; nulo cai em
    `_complete()` — a matricula termina calada no meio do fluxo."""
    campanha, nos = _grafo()
    _por_id(nos, "cond")["yes_node_id"] = None

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "condicao_incompleta"
    assert problemas[0].no_id == "cond"
    assert "SIM" in problemas[0].mensagem


def test_condicao_sem_ramo_nao():
    campanha, nos = _grafo()
    _por_id(nos, "cond")["no_node_id"] = None

    problemas = validar(campanha, nos, TEMPLATES)

    # O ramo NAO era o unico caminho ate o toque 2: cortar a saida orfana o toque.
    assert _codigos(problemas) == ["condicao_incompleta", "no_inalcancavel"]
    incompleta = _de(problemas, "condicao_incompleta")
    assert len(incompleta) == 1 and incompleta[0].no_id == "cond"
    assert "NÃO" in incompleta[0].mensagem


def test_next_node_id_numa_condicao_nao_conta_como_saida():
    """O motor sai de uma condicao SO por yes/no (`engine._execute_condition` nem olha
    o `next_node_id`). Seguir essa seta aqui marcaria como alcancavel um trecho que
    nunca executa — falso negativo que apaga justamente o aviso de que aquele pedaco
    do canvas e letra morta."""
    campanha, nos = _grafo()
    _por_id(nos, "cond")["next_node_id"] = "solto"
    nos.append(_no("solto", "wait", {"days": 1}, prox="fim"))

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "no_inalcancavel"
    assert problemas[0].no_id == "solto"


def test_no_do_meio_sem_saida():
    """A FK de `next_node_id` e ON DELETE SET NULL: apagar um no do meio deixa o
    antecessor com a seta nula e toda matricula que chega ali termina em silencio."""
    campanha, _ = _grafo()
    nos = [
        _no("gat", "trigger", _GATILHO_OK, prox="t1"),
        _no("t1", "send", {"template_name": T1}, prox="esp"),
        _no("esp", "wait", {"days": 3}),  # o no seguinte foi apagado
    ]

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "no_sem_saida"
    assert problemas[0].no_id == "esp"

    # O outro lado da regra: o no de FIM nao tem saida por definicao.
    assert not _de(validar(*_grafo(), TEMPLATES), "no_sem_saida")


def test_ciclo_no_grafo():
    campanha, _ = _grafo()
    nos = [
        _no("gat", "trigger", _GATILHO_OK, prox="t1"),
        _no("t1", "send", {"template_name": T1}, prox="esp"),
        _no("esp", "wait", {"days": 3}, prox="t1"),  # volta para o toque 1
    ]

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "ciclo"
    assert "toque 1" in problemas[0].mensagem and "Aguardar" in problemas[0].mensagem

    # E o losango do grafo-base (SIM e NAO desaguando no mesmo `fim`) NAO e ciclo.
    assert not _de(validar(*_grafo(), TEMPLATES), "ciclo")


# ── Campanha (regras 11 a 13) ────────────────────────────────────────────────────


def test_sem_canal_na_campanha_e_sem_canal_no_no_de_envio():
    campanha, nos = _grafo()
    campanha["channel_id"] = None

    problemas = validar(campanha, nos, TEMPLATES)

    assert _codigos(problemas) == ["sem_canal", "sem_canal"]
    assert {p.no_id for p in problemas} == {"t1", "t2"}


def test_canal_proprio_no_no_dispensa_o_canal_da_campanha():
    campanha, nos = _grafo()
    campanha["channel_id"] = None
    for nid in ("t1", "t2"):
        _por_id(nos, nid)["config"]["channel_id"] = CANAL

    assert validar(campanha, nos, TEMPLATES) == []


def test_template_ausente_da_meta():
    """O estado inicial deste projeto: os templates `esteira_*` que o seed referencia
    nunca foram submetidos. A acao aqui e CRIAR o template — dizer so "nao esta
    aprovado" manda o operador procurar na Meta uma linha que nao existe."""
    campanha, nos = _grafo()
    _por_id(nos, "t2")["config"]["template_name"] = "esteira_reposicao_t3"

    problemas = validar(campanha, nos, TEMPLATES)

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "template_nao_aprovado"
    assert problemas[0].no_id == "t2"
    assert "esteira_reposicao_t3" in problemas[0].mensagem
    assert "NÃO EXISTE" in problemas[0].mensagem
    assert "toque 2" in problemas[0].mensagem, (
        "a mensagem e lida pelo operador: ele precisa saber QUAL toque abrir")


def test_template_pendente_na_meta():
    """PENDING: existe e esta certo — a acao e ESPERAR."""
    campanha, nos = _grafo()
    problemas = validar(campanha, nos, {**TEMPLATES, T2: "PENDING"})

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "template_nao_aprovado"
    assert problemas[0].no_id == "t2"
    assert T2 in problemas[0].mensagem
    assert "PENDING" in problemas[0].mensagem
    assert "Espere" in problemas[0].mensagem
    assert "NÃO EXISTE" not in problemas[0].mensagem


def test_template_rejeitado_na_meta():
    """REJECTED: esperar nao resolve nunca — a acao e CORRIGIR e ressubmeter."""
    campanha, nos = _grafo()
    problemas = validar(campanha, nos, {**TEMPLATES, T2: "REJECTED"})

    assert len(problemas) == 1, _codigos(problemas)
    assert problemas[0].codigo == "template_nao_aprovado"
    assert "REJECTED" in problemas[0].mensagem
    assert "recusou" in problemas[0].mensagem
    assert "Espere" not in problemas[0].mensagem, (
        "esperar e a acao do PENDING; no REJECTED ela e conselho errado")


def test_status_aprovado_em_minusculo_e_aceito():
    """O sync local grava `message_templates.status` em minusculo e o payload cru da
    Meta vem 'APPROVED'. Comparar sem normalizar reprovaria template aprovado — e o
    operador nao teria o que consertar, porque nao ha nada errado."""
    campanha, nos = _grafo()

    assert validar(campanha, nos, {T1: "approved", T2: "APPROVED"}) == []


def test_mapa_vazio_nao_e_o_mesmo_que_none():
    """Mapa vazio e uma RESPOSTA ("a Meta nao conhece nenhum desses"), nao uma falha de
    consulta: reprova os dois toques. So `None` e fail-open."""
    campanha, nos = _grafo()

    problemas = validar(campanha, nos, {})

    assert _codigos(problemas) == ["template_nao_aprovado", "template_nao_aprovado"]
    assert {p.no_id for p in problemas} == {"t1", "t2"}


def test_templates_none_pula_so_a_regra_do_template():
    """Fail-open quando a consulta a `message_templates` falha (mesmo criterio do
    `esteiras_router._nao_aprovados`): um timeout do Supabase nao pode travar a
    ativacao inteira — mas tambem nao pode servir de anistia para o resto."""
    campanha, nos = _grafo()
    _por_id(nos, "t2")["config"]["template_name"] = "template_que_nao_existe"
    _por_id(nos, "cond")["yes_node_id"] = None  # violacao de OUTRA regra

    problemas = validar(campanha, nos, None)

    assert _codigos(problemas) == ["condicao_incompleta"]


def test_grafo_valido_nao_tem_problema():
    campanha, nos = _grafo()

    assert validar(campanha, nos, TEMPLATES) == []
    assert isinstance(Problema(None, "ciclo", "x"), Problema)

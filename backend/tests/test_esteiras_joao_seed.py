"""Seed das 6 esteiras do vendedor Joao (reuniao de 10/09/2026, Task 9).

Decisoes da reuniao que este seed materializa (ver `app/campaigns/esteiras_joao.py`):

- "Novo": card parado na etapa `novo` — a ata falou "36h a dois dias"; usamos DOIS DIAS
  porque `deal_stage_stagnation` e o unico gatilho COMPLETO do sistema (o unico com
  guarda de blacklist, numero errado e conversa finalizada) e ele so entende dias
  inteiros na RPC `get_deals_stage_stagnant` (`p_stage_days int`) — nao ha granularidade
  de horas. 36h exigiria um gatilho novo so para isto; dois dias fica dentro do que o
  dono aprovou e reusa o gatilho mais seguro que existe.
- "Em conversa": 7 toques em 30 dias (D+2/4/7/12/18/24/30), `on_reply='reset'` — qualquer
  resposta do lead rebobina para D+0. Termina em `em_atencao`.
- "Reposicao": card em "Cliente Ativo" (key `novo` do funil de reposicao) ha 45 dias,
  depois toques de 3, 15 e 15 dias. Termina em `em_atencao`.

Cada esteira existe 2x (Atacado / Private Label) porque o gatilho e por funil e as
mensagens diferem — 6 campanhas ao todo, todas no canal do Joao.
"""
from unittest.mock import MagicMock, patch

from app.campaigns import esteiras_joao
from app.campaigns.service import _ENV_TAG

_FUNIS_ATACADO = {esteiras_joao.PIPELINE_ATACADO, esteiras_joao.PIPELINE_REPOSICAO_ATACADO}
_FUNIS_PL = {esteiras_joao.PIPELINE_PRIVATE_LABEL, esteiras_joao.PIPELINE_REPOSICAO_PRIVATE_LABEL}


def _trigger(e: dict) -> dict:
    return next(n for n in e["nodes"] if n["type"] == "trigger")


def _por_prefixo(prefixo: str) -> list[dict]:
    return [e for e in esteiras_joao.ESTEIRAS_JOAO if e["key"].startswith(prefixo)]


def _intervalos(e: dict, largada: int | None) -> list[int]:
    """[largada ou stage_days do gatilho] + [dias de cada `wait`, em ordem]."""
    trigger = _trigger(e)
    primeiro = trigger["config"]["stage_days"] if largada is None else largada
    waits = [n["config"]["days"] for n in e["nodes"] if n["type"] == "wait"]
    return [primeiro] + waits


# ── Forma geral: 6 esteiras, 3 por funil ─────────────────────────────────────────


def test_seis_esteiras_ao_todo():
    assert len(esteiras_joao.ESTEIRAS_JOAO) == 6
    assert len({e["key"] for e in esteiras_joao.ESTEIRAS_JOAO}) == 6


def test_tres_esteiras_por_funil():
    atacado = [e for e in esteiras_joao.ESTEIRAS_JOAO if _trigger(e)["config"]["pipeline_id"] in _FUNIS_ATACADO]
    pl = [e for e in esteiras_joao.ESTEIRAS_JOAO if _trigger(e)["config"]["pipeline_id"] in _FUNIS_PL]
    assert len(atacado) == 3
    assert len(pl) == 3
    # nenhuma esteira fica sem funil reconhecido (typo silencioso num uuid)
    assert len(atacado) + len(pl) == len(esteiras_joao.ESTEIRAS_JOAO)


def test_todas_nascem_em_draft():
    """Nada dispara sozinho: o motor so processa campanha 'active'."""
    for e in esteiras_joao.ESTEIRAS_JOAO:
        assert e["status"] == "draft"


def test_todas_com_audience_humano():
    """'ia' (o default da coluna) ignoraria todo lead do Joao: RPC filtra
    `l.ai_enabled = TRUE` para audience='ia', e o lead do vendedor tem ai_enabled=False
    depois do handoff. Se alguem trocar para 'ia' por engano, este teste acusa."""
    for e in esteiras_joao.ESTEIRAS_JOAO:
        assert e["audience"] == "humano"


def test_todas_no_canal_do_joao():
    for e in esteiras_joao.ESTEIRAS_JOAO:
        assert e["channel_id"] == esteiras_joao.CANAL_JOAO


def test_frequency_cap_um():
    for e in esteiras_joao.ESTEIRAS_JOAO:
        assert e["frequency_cap"] == 1


def test_gatilhos_sao_deal_stage_stagnation():
    for e in esteiras_joao.ESTEIRAS_JOAO:
        assert _trigger(e)["config"]["trigger_type"] == "deal_stage_stagnation"


def test_templates_ficam_em_branco_para_o_dono_preencher():
    """Ligar a esteira exige template aprovado (regra da tela) — o seed nao pode
    adivinhar qual template usar."""
    for e in esteiras_joao.ESTEIRAS_JOAO:
        for no in e["nodes"]:
            if no["type"] == "send":
                assert no["config"]["template_name"] == ""


# ── IDs deterministicos e distintos ──────────────────────────────────────────────


def test_campaign_ids_deterministicos_e_distintos():
    ids = [e["campaign_id"] for e in esteiras_joao.ESTEIRAS_JOAO]
    assert len(set(ids)) == 6
    # pura: mesma chave + mesmo env_tag -> mesmo id sempre
    outra_chamada = [esteiras_joao._campaign_id(e["key"], _ENV_TAG) for e in esteiras_joao.ESTEIRAS_JOAO]
    assert ids == outra_chamada


def test_ids_isolados_por_ambiente():
    """dev e producao compartilham o mesmo Supabase — sem o env_tag no namespace,
    quem subisse primeiro carimbaria o outro ambiente sem campanha."""
    dev = esteiras_joao._campaign_id("novo_atacado", "dev")
    prod = esteiras_joao._campaign_id("novo_atacado", "production")
    assert dev != prod


# ── "Novo": stage_days=2 na etapa 'novo' ─────────────────────────────────────────


def test_novo_gatilho_etapa_novo_stage_days_dois():
    esteiras = _por_prefixo("novo_")
    assert len(esteiras) == 2
    for e in esteiras:
        trigger = _trigger(e)
        assert trigger["config"]["stage_key"] == "novo"
        assert trigger["config"]["stage_days"] == 2


def test_novo_nao_move_o_card():
    """Um toque de retomada, sem acao final — nao mexe no Kanban."""
    for e in _por_prefixo("novo_"):
        assert not any(n["type"] == "action" for n in e["nodes"])
        assert sum(1 for n in e["nodes"] if n["type"] == "send") == 1


# ── "Em conversa": 7 toques, D+2/4/7/12/18/24/30, on_reply='reset' ──────────────


def test_em_conversa_gatilho_etapa_respondeu_e_reset():
    esteiras = _por_prefixo("em_conversa_")
    assert len(esteiras) == 2
    for e in esteiras:
        trigger = _trigger(e)
        assert trigger["config"]["stage_key"] == "respondeu"
        assert trigger["config"]["on_reply"] == "reset"


def test_em_conversa_sete_toques_intervalos_dois_quatro_sete_doze_dezoito_vinteequatro_trinta():
    for e in _por_prefixo("em_conversa_"):
        assert sum(1 for n in e["nodes"] if n["type"] == "send") == 7
        # deltas de D+2/4/7/12/18/24/30 a partir de D+0: [2, 2, 3, 5, 6, 6, 6].
        # O primeiro elemento e o proprio stage_days do gatilho (o toque 1 sai assim
        # que a esteira dispara, e ela dispara aos 2 dias na etapa).
        assert _intervalos(e, largada=None) == [2, 2, 3, 5, 6, 6, 6]


def test_em_conversa_send_nao_sobrescreve_on_reply_do_gatilho():
    """`worker._apply_reply_policy` da precedencia ao NO sobre o GATILHO. Um
    on_reply='cancel' hardcoded no `send` mataria o reset silenciosamente."""
    for e in _por_prefixo("em_conversa_"):
        for no in e["nodes"]:
            if no["type"] == "send":
                assert "on_reply" not in no["config"]


# ── "Reposicao": stage_days=45, toques de 3/15/15 ────────────────────────────────


def test_reposicao_stage_days_45():
    esteiras = _por_prefixo("reposicao_")
    assert len(esteiras) == 2
    for e in esteiras:
        trigger = _trigger(e)
        assert trigger["config"]["stage_key"] == "novo"  # key da etapa "Cliente Ativo"
        assert trigger["config"]["stage_days"] == 45


def test_reposicao_intervalos_zero_tres_quinze_quinze():
    for e in _por_prefixo("reposicao_"):
        assert sum(1 for n in e["nodes"] if n["type"] == "send") == 4
        # o toque 1 sai no disparo do gatilho (delta 0 a partir do proprio disparo);
        # os 15/15 seguintes sao esperas ENTRE toques, nao do gatilho.
        assert _intervalos(e, largada=0) == [0, 3, 15, 15]


# ── "Em conversa" e "Reposicao" terminam em em_atencao; "Novo" nao termina em nada ──


def test_em_conversa_e_reposicao_terminam_movendo_para_em_atencao():
    for e in _por_prefixo("em_conversa_") + _por_prefixo("reposicao_"):
        acoes = [n["config"] for n in e["nodes"] if n["type"] == "action"]
        assert len(acoes) == 1
        assert acoes[0]["action_type"] == "move_deal_stage"
        assert acoes[0]["stage_key"] == "em_atencao"
        # stage_id fica None de proposito: nao temos o uuid de em_atencao por funil
        # nesta lista (so os 4 funis + o canal foram dados) — fica para a tela/router
        # resolver, mesmo padrao do `mark_deal_lost` do esteiras.py generico.
        assert acoes[0]["stage_id"] is None


# ── Grafo ligado: todo no aponta para um id que existe no proprio grafo ─────────


def test_grafo_ligado_e_termina_em_end():
    for e in esteiras_joao.ESTEIRAS_JOAO:
        ids_no_grafo = {n["id"] for n in e["nodes"]}
        assert len(ids_no_grafo) == len(e["nodes"]), f"id duplicado em {e['key']}"
        for i, no in enumerate(e["nodes"]):
            if i == len(e["nodes"]) - 1:
                assert no["type"] == "end"
            else:
                proximo = e["nodes"][i + 1]["id"]
                assert proximo in ids_no_grafo, f"no orfao em {e['key']}: {no['id']}"
        assert sum(1 for n in e["nodes"] if n["type"] == "end") == 1
        assert sum(1 for n in e["nodes"] if n["type"] == "trigger") == 1
        assert e["nodes"][0]["type"] == "trigger"


def test_build_node_rows_encadeamento_bate_com_a_lista_de_nos():
    """`build_node_rows` e quem realmente vira o FK `next_node_id` gravado — a
    fonte de verdade da topologia, nao so a ordem da lista `nodes`."""
    for e in esteiras_joao.ESTEIRAS_JOAO:
        rows = {r["id"]: r for r in esteiras_joao.build_node_rows(e)}
        assert len(rows) == len(e["nodes"])
        for i, no in enumerate(e["nodes"]):
            esperado = e["nodes"][i + 1]["id"] if i + 1 < len(e["nodes"]) else None
            assert rows[no["id"]]["next_node_id"] == esperado
            assert rows[no["id"]]["campaign_id"] == e["campaign_id"]
        trigger = _trigger(e)
        assert rows[trigger["id"]]["next_node_id"] is not None


def test_nos_inseridos_em_ordem_topologica_reversa():
    """FK next_node_id aponta para campaign_nodes: o alvo tem de existir antes."""
    for e in esteiras_joao.ESTEIRAS_JOAO:
        rows = esteiras_joao.build_node_rows(e)
        vistos: set[str] = set()
        for r in rows:
            if r["next_node_id"] is not None:
                assert r["next_node_id"] in vistos, "no inserido antes do alvo do FK"
            vistos.add(r["id"])


# ── Seed: idempotencia e fail-soft ───────────────────────────────────────────────


def _sb(campanhas_existentes=None, nos_existentes=None):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.in_.return_value
       .execute.return_value.data) = campanhas_existentes or []
    (sb.table.return_value.select.return_value.eq.return_value.limit.return_value
       .execute.return_value.data) = nos_existentes if nos_existentes is not None else [{"id": "n"}]
    return sb


def _payloads(sb):
    return [c[0][0] for c in sb.table.return_value.insert.call_args_list]


def test_seed_cria_as_seis():
    sb = _sb()
    with patch("app.campaigns.esteiras_joao.get_supabase", return_value=sb):
        esteiras_joao.seed_esteiras_joao()
    campanhas = [p for p in _payloads(sb) if isinstance(p, dict)]
    assert len(campanhas) == 6
    assert {c["status"] for c in campanhas} == {"draft"}
    assert {c["env_tag"] for c in campanhas} == {_ENV_TAG}
    assert {c["audience"] for c in campanhas} == {"humano"}
    assert {c["channel_id"] for c in campanhas} == {esteiras_joao.CANAL_JOAO}


def test_seed_nao_sobrescreve_campanha_existente_rodar_duas_vezes_e_no_op():
    """Idempotencia por EXISTENCIA do id: rodar de novo com as 6 ja no banco nao
    escreve nada."""
    sb = _sb([{"id": e["campaign_id"]} for e in esteiras_joao.ESTEIRAS_JOAO])
    with patch("app.campaigns.esteiras_joao.get_supabase", return_value=sb):
        esteiras_joao.seed_esteiras_joao()
    sb.table.return_value.insert.assert_not_called()
    sb.table.return_value.update.assert_not_called()
    sb.table.return_value.delete.assert_not_called()


def test_seed_repara_campanha_criada_sem_nos():
    sb = _sb([{"id": e["campaign_id"]} for e in esteiras_joao.ESTEIRAS_JOAO], nos_existentes=[])
    with patch("app.campaigns.esteiras_joao.get_supabase", return_value=sb):
        esteiras_joao.seed_esteiras_joao()
    payloads = _payloads(sb)
    assert all(isinstance(p, list) for p in payloads), "nao pode reinserir a campanha"
    assert len(payloads) == 6


def test_seed_fail_soft_na_consulta():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("boom")
    with patch("app.campaigns.esteiras_joao.get_supabase", return_value=sb):
        esteiras_joao.seed_esteiras_joao()  # nao levanta


def test_falha_numa_esteira_nao_impede_as_outras():
    sb = _sb()
    chamadas = {"n": 0}

    def _insert(payload):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("coluna audience ainda nao existe")
        return MagicMock()

    sb.table.return_value.insert.side_effect = _insert
    with patch("app.campaigns.esteiras_joao.get_supabase", return_value=sb):
        esteiras_joao.seed_esteiras_joao()
    # 1 falhou; as outras 5 seguiram (campanha + nos cada uma)
    assert chamadas["n"] >= 11

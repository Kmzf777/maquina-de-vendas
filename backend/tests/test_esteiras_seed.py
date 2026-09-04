"""Seed das 4 campanhas de esteira: idempotente e NAO destrutivo.

Contrato que este arquivo fixa:

1. FORMA DAS ESTEIRAS — publico, prioridade, teto de frequencia, numero de toques e
   acao final de cada uma (spec §4).
2. NAO-DESTRUTIVIDADE — ao contrario de `system_cadence.py` (espelho re-sincronizado a
   cada deploy), este seed cria UMA VEZ e nunca sobrescreve: a decisao do dono e que o
   Arthur e o Joao editem prazo e template pela tela, sem deploy.
3. EXECUTABILIDADE — o grafo tem de ser valido para o motor: gatilho conectado (sem
   `next_node_id` o gatilho nem enrolla), todo caminho chega num `end`, e os parametros
   de template usam so tokens que o caminho de envio sabe resolver.
"""
from unittest.mock import MagicMock, patch

from app.broadcast.worker import _LEAD_FIELD_TOKENS
from app.campaigns import esteiras
from app.campaigns.service import _ENV_TAG

# Tipos que o builder React Flow renderiza (frontend/src/lib/types.ts CampaignNodeType)
_BUILDER_NODE_TYPES = {"trigger", "send", "send_text", "wait", "condition", "action", "end"}


def _esteira(key: str) -> dict:
    return next(e for e in esteiras.ESTEIRAS if e["key"] == key)


# ── Forma das esteiras ───────────────────────────────────────────────────────────


def test_quatro_esteiras_com_ids_deterministicos():
    ids = {e["key"]: e["campaign_id"] for e in esteiras.ESTEIRAS}
    assert set(ids) == {"novo_sem_resposta", "novo_reengajamento", "reposicao", "proposta"}
    # ids estaveis entre execucoes
    assert ids == {e["key"]: e["campaign_id"] for e in esteiras.ESTEIRAS}
    assert len(set(ids.values())) == 4


def test_ids_isolados_por_ambiente():
    """dev e producao compartilham o mesmo Supabase. Com id fixo, quem subisse
    primeiro carimbaria o `env_tag` e o outro ambiente nunca veria as campanhas —
    `get_campaigns_with_trigger_type` filtra por env_tag, entao a esteira ficaria
    ativa e muda."""
    dev = esteiras._campaign_id("reposicao", "dev")
    prod = esteiras._campaign_id("reposicao", "production")
    assert dev != prod
    assert _esteira("reposicao")["campaign_id"] == esteiras._campaign_id("reposicao", _ENV_TAG)


def test_todas_nascem_em_draft():
    for e in esteiras.ESTEIRAS:
        assert e["status"] == "draft"


def test_todas_com_audience_humano():
    """As esteiras existem justamente para o lead pos-handoff (ai_enabled=False)."""
    for e in esteiras.ESTEIRAS:
        assert e["audience"] == "humano"


def test_prioridade_proposta_maior_que_novo_maior_que_reposicao():
    p = {e["key"]: e["priority"] for e in esteiras.ESTEIRAS}
    assert p["proposta"] > p["novo_sem_resposta"] == p["novo_reengajamento"] > p["reposicao"]


def test_frequency_cap_um():
    for e in esteiras.ESTEIRAS:
        assert e["frequency_cap"] == 1


def test_envios_cancelam_no_reply():
    """on_reply='pause' deixaria o lead inelegivel para sempre (enrollment pausado
    conta como ativo em is_already_enrolled e nunca e retomado)."""
    for e in esteiras.ESTEIRAS:
        for no in e["nodes"]:
            if no["type"] == "send":
                assert no["config"]["on_reply"] == "cancel"


def test_gatilho_carrega_on_reply_cancel():
    """Nao basta nos nos de envio: a esteira fica parada num `wait` a maior parte do
    tempo, e e la que a maioria das respostas chega."""
    for e in esteiras.ESTEIRAS:
        trigger = next(n for n in e["nodes"] if n["type"] == "trigger")
        assert trigger["config"]["on_reply"] == "cancel"


def test_reposicao_tem_tres_toques_e_termina_em_mark_deal_lost():
    e = _esteira("reposicao")
    assert sum(1 for n in e["nodes"] if n["type"] == "send") == 3
    acoes = [n["config"].get("action_type") for n in e["nodes"] if n["type"] == "action"]
    assert "mark_deal_lost" in acoes


def test_proposta_tem_dois_toques_e_termina_em_alert_seller():
    e = _esteira("proposta")
    assert sum(1 for n in e["nodes"] if n["type"] == "send") == 2
    acoes = [n["config"].get("action_type") for n in e["nodes"] if n["type"] == "action"]
    assert "alert_seller" in acoes
    assert "mark_deal_lost" not in acoes  # proposta nunca vira perdido sozinha


def test_esteira_novo_sem_resposta_filtra_falante_lead():
    trigger = next(n for n in _esteira("novo_sem_resposta")["nodes"] if n["type"] == "trigger")
    assert trigger["config"]["last_speaker"] == "lead"


def test_esteira_novo_reengajamento_filtra_falante_nos():
    trigger = next(n for n in _esteira("novo_reengajamento")["nodes"] if n["type"] == "trigger")
    assert trigger["config"]["last_speaker"] == "nos"


def test_gatilhos_sao_deal_stage_stagnation():
    for e in esteiras.ESTEIRAS:
        trigger = next(n for n in e["nodes"] if n["type"] == "trigger")
        assert trigger["config"]["trigger_type"] == "deal_stage_stagnation"


def test_proposta_conta_dias_de_etapa_e_as_outras_contam_silencio():
    """A ata: 'proposta enviada conta tres dias' — relogio da ETAPA, nao da conversa."""
    proposta = next(n for n in _esteira("proposta")["nodes"] if n["type"] == "trigger")
    assert proposta["config"]["stage_days"] == 3
    assert proposta["config"]["stage_key"] == "proposta_enviada"
    for key, dias in (("novo_sem_resposta", 3), ("novo_reengajamento", 3), ("reposicao", 15)):
        cfg = next(n for n in _esteira(key)["nodes"] if n["type"] == "trigger")["config"]
        assert cfg["silence_days"] == dias
        assert cfg["stage_days"] == 0


# ── Executabilidade do grafo ─────────────────────────────────────────────────────


def test_tipos_de_no_sao_validos_para_o_builder():
    for e in esteiras.ESTEIRAS:
        assert all(n["type"] in _BUILDER_NODE_TYPES for n in e["nodes"])


def test_gatilho_conectado_e_encadeamento_linear():
    """`triggers.check_polling_triggers` faz `if not tn.get('next_node_id'): continue` —
    gatilho solto nao enrolla ninguem, silenciosamente."""
    for e in esteiras.ESTEIRAS:
        rows = {r["id"]: r for r in esteiras.build_node_rows(e)}
        assert len(rows) == len(e["nodes"])
        for i, no in enumerate(e["nodes"]):
            esperado = e["nodes"][i + 1]["id"] if i + 1 < len(e["nodes"]) else None
            assert rows[no["id"]]["next_node_id"] == esperado
            assert rows[no["id"]]["campaign_id"] == e["campaign_id"]
        trigger = next(n for n in e["nodes"] if n["type"] == "trigger")
        assert rows[trigger["id"]]["next_node_id"] is not None


def test_toda_esteira_termina_num_end():
    for e in esteiras.ESTEIRAS:
        assert e["nodes"][-1]["type"] == "end"
        assert sum(1 for n in e["nodes"] if n["type"] == "end") == 1
        assert sum(1 for n in e["nodes"] if n["type"] == "trigger") == 1
        assert e["nodes"][0]["type"] == "trigger"


def test_nos_sao_inseridos_em_ordem_topologica_reversa():
    """O FK next_node_id aponta para campaign_nodes: o alvo tem de existir antes."""
    for e in esteiras.ESTEIRAS:
        rows = esteiras.build_node_rows(e)
        vistos: set[str] = set()
        for r in rows:
            if r["next_node_id"] is not None:
                assert r["next_node_id"] in vistos, "no inserido antes do alvo do FK"
            vistos.add(r["id"])


def test_parametros_de_template_sao_posicionais():
    """Os 5 templates da spec §7 usam {{1}}/{{2}}. Sem __params_type__ o
    _build_template_components monta `parameter_name` (named) e a Meta recusa."""
    for e in esteiras.ESTEIRAS:
        for no in e["nodes"]:
            if no["type"] == "send":
                assert no["config"]["template_variables"]["__params_type__"] == "positional"
                assert no["config"]["template_name"]
                assert no["config"]["template_language"]


def test_parametro_de_template_nao_usa_token_irresolvivel():
    """O caminho de template resolve tokens por `broadcast.worker._resolve_value`, que
    conhece uma lista FECHADA. `{{nome}}`/`{{vendedor}}` so existem em
    `automation.variables.substitute_variables` (texto livre e alertas) — num parametro
    de template eles seriam enviados LITERALMENTE para o cliente."""
    for e in esteiras.ESTEIRAS:
        for no in e["nodes"]:
            if no["type"] != "send":
                continue
            for chave, valor in no["config"]["template_variables"].items():
                if str(chave).startswith("__"):
                    continue
                if "{{" in str(valor):
                    assert valor in _LEAD_FIELD_TOKENS, f"token irresolvivel: {valor}"


# ── Seed ─────────────────────────────────────────────────────────────────────────


def _sb(campanhas_existentes=None, nos_existentes=None):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.in_.return_value
       .execute.return_value.data) = campanhas_existentes or []
    (sb.table.return_value.select.return_value.eq.return_value.limit.return_value
       .execute.return_value.data) = nos_existentes if nos_existentes is not None else [{"id": "n"}]
    return sb


def _payloads(sb):
    return [c[0][0] for c in sb.table.return_value.insert.call_args_list]


def test_seed_nao_sobrescreve_campanha_existente():
    sb = _sb([{"id": e["campaign_id"]} for e in esteiras.ESTEIRAS])
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    sb.table.return_value.insert.assert_not_called()
    sb.table.return_value.update.assert_not_called()
    sb.table.return_value.delete.assert_not_called()


def test_seed_cria_o_que_falta():
    sb = _sb()
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    assert sb.table.return_value.insert.call_count >= 4
    campanhas = [p for p in _payloads(sb) if isinstance(p, dict)]
    assert len(campanhas) == 4
    assert {c["status"] for c in campanhas} == {"draft"}
    assert {c["env_tag"] for c in campanhas} == {_ENV_TAG}
    assert {c["audience"] for c in campanhas} == {"humano"}


def test_seed_grava_todos_os_nos():
    sb = _sb()
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    inseridos = [r for p in _payloads(sb) if isinstance(p, list) for r in p]
    assert len(inseridos) == sum(len(e["nodes"]) for e in esteiras.ESTEIRAS)


def test_seed_repara_campanha_criada_sem_nos():
    """Falha no meio do seed (campanha inserida, nos nao) deixaria uma campanha vazia
    para sempre — idempotencia por existencia do id nunca mais voltaria nela."""
    sb = _sb([{"id": e["campaign_id"]} for e in esteiras.ESTEIRAS], nos_existentes=[])
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    payloads = _payloads(sb)
    assert all(isinstance(p, list) for p in payloads), "nao pode reinserir a campanha"
    assert len(payloads) == 4


def test_seed_fail_soft():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("boom")
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()  # nao levanta


def test_falha_numa_esteira_nao_impede_as_outras():
    sb = _sb()
    chamadas = {"n": 0}

    def _insert(payload):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("coluna audience ainda nao existe")
        return MagicMock()

    sb.table.return_value.insert.side_effect = _insert
    with patch("app.campaigns.esteiras.get_supabase", return_value=sb):
        esteiras.seed_esteiras()
    # 1 falhou; as outras 3 seguiram (campanha + nos cada uma)
    assert chamadas["n"] >= 7

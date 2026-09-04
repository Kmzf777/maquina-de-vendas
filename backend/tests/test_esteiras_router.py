"""API achatada das esteiras: le e grava PARAMETRO, nunca topologia.

Contrato que este arquivo fixa (a aba /campanhas > Esteiras escreve contra ele):

1. LEITURA VEM DO BANCO, na ordem do GRAFO. O seed insere os nos em ordem topologica
   REVERSA (o FK `next_node_id` exige o alvo antes), entao confiar na ordem que o
   PostgREST devolve inverteria os toques — t3 apareceria como toque 1.
2. ESCRITA E PARCIAL E NAO DESTRUTIVA. Um PUT que so desliga a esteira nao pode
   devolver o gatilho aos defaults do seed (que tem `stage_id: None`).
3. LIGAR EXIGE ETAPA. Na RPC `get_deals_stage_stagnant`, `p_stage_id IS NULL` E
   `p_stage_key IS NULL` significam "sem filtro de etapa" — fail-open. Uma esteira
   ligada antes de configurada ficaria elegivel a todo card aberto de todo funil,
   20 por tick.
4. A ETAPA DE PERDIDO DA REPOSICAO E RESOLVIDA PELA API. O seed nasce com
   `stage_id: None` no `mark_deal_lost` e `engine._execute_action` retorna cedo sem
   ele: a esteira rodaria os tres toques e terminaria sem mover o card.
"""
import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.campaigns import esteiras as seed
from app.campaigns import esteiras_router


# ── Fake Supabase (chainable, com estado) ────────────────────────────────────────
# MagicMock puro nao serve aqui: o router LE linhas e depois decide o que gravar; um
# mock devolveria MagicMock nao-iteravel e o teste passaria por acidente.


class _Query:
    def __init__(self, sb, tabela: str):
        self.sb = sb
        self.tabela = tabela
        self._modo = "select"
        self._payload = None
        self._filtros: list[tuple] = []
        self._limite = None
        self._ordem = None

    def select(self, *_a, **_k):
        self._modo = "select"
        return self

    def update(self, payload):
        self._modo = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._modo = "insert"
        self._payload = payload
        return self

    def delete(self):
        self._modo = "delete"
        return self

    def eq(self, col, val):
        self._filtros.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self._filtros.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._ordem = (col, desc)
        return self

    def limit(self, n):
        self._limite = n
        return self

    def _casa(self, row) -> bool:
        for tipo, col, val in self._filtros:
            if tipo == "eq" and row.get(col) != val:
                return False
            if tipo == "in" and row.get(col) not in val:
                return False
        return True

    def execute(self):
        if self._modo in ("update", "insert", "delete"):
            self.sb.escritas.append((self.tabela, self._modo, self._payload,
                                     list(self._filtros)))
            return SimpleNamespace(data=[])
        linhas = [copy.deepcopy(r) for r in self.sb.dados.get(self.tabela, []) if self._casa(r)]
        if self._ordem and all(self._ordem[0] in r for r in linhas):
            linhas.sort(key=lambda r: r[self._ordem[0]], reverse=self._ordem[1])
        if self._limite is not None:
            linhas = linhas[: self._limite]
        return SimpleNamespace(data=linhas)


class _FakeSB:
    def __init__(self, dados: dict[str, list[dict]]):
        self.dados = dados
        self.escritas: list[tuple] = []

    def table(self, nome: str) -> _Query:
        return _Query(self, nome)

    # helpers de asserção
    def updates(self, tabela: str) -> list[tuple[dict, dict]]:
        """[(payload, {coluna: valor dos filtros eq})] das escritas de update."""
        out = []
        for t, modo, payload, filtros in self.escritas:
            if t == tabela and modo == "update":
                out.append((payload, {c: v for tipo, c, v in filtros if tipo == "eq"}))
        return out


def _esteira(key: str) -> dict:
    return next(e for e in seed.ESTEIRAS if e["key"] == key)


def _linhas_campanhas(status: dict[str, str] | None = None, channel_id=None) -> list[dict]:
    status = status or {}
    return [
        {"id": e["campaign_id"], "status": status.get(e["key"], "draft"),
         "channel_id": channel_id, "env_tag": "dev"}
        for e in seed.ESTEIRAS
    ]


def _linhas_nos() -> list[dict]:
    """Nos como o seed os grava: ORDEM TOPOLOGICA REVERSA (end primeiro).

    deepcopy obrigatorio: `build_node_rows` devolve o MESMO objeto `config` dos nos do
    modulo (nao copia), entao editar a linha "do banco" no teste mutaria o seed global
    e vazaria para os testes seguintes.
    """
    linhas: list[dict] = []
    for e in seed.ESTEIRAS:
        linhas.extend(copy.deepcopy(seed.build_node_rows(e)))
    return linhas


def _banco(status=None, channel_id=None, stages=None) -> _FakeSB:
    return _FakeSB({
        "campaigns": _linhas_campanhas(status, channel_id),
        "campaign_nodes": _linhas_nos(),
        "pipeline_stages": stages or [],
    })


def _com(sb):
    return patch("app.campaigns.esteiras_router.get_supabase", return_value=sb)


def _no_do_banco(sb, node_id: str) -> dict:
    return next(n for n in sb.dados["campaign_nodes"] if n["id"] == node_id)


# ── GET ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_devolve_as_quatro_esteiras():
    with _com(_banco()):
        out = await esteiras_router.listar_esteiras()
    assert {e["key"] for e in out["esteiras"]} == {
        "novo_sem_resposta", "novo_reengajamento", "reposicao", "proposta"}
    assert len(out["esteiras"]) == 4


@pytest.mark.asyncio
async def test_get_marca_ativa_quando_status_active():
    with _com(_banco(status={"reposicao": "active"})):
        out = await esteiras_router.listar_esteiras()
    ativa = {e["key"]: e["ativa"] for e in out["esteiras"]}
    assert ativa["reposicao"] is True
    assert ativa["proposta"] is False


@pytest.mark.asyncio
async def test_get_devolve_toques_na_ordem_do_grafo():
    """O seed insere em ordem topologica REVERSA. Sem seguir o `next_node_id`, o
    toque 3 apareceria como toque 1 e a tela mostraria o prazo errado."""
    sb = _banco()
    e = _esteira("reposicao")
    # prazos distintos por espera para flagrar troca de ordem
    for i, dias in enumerate((11, 12, 13)):
        _no_do_banco(sb, e["nodes"][2 + i * 2]["id"])["config"]["days"] = dias
    with _com(sb):
        out = await esteiras_router.listar_esteiras()
    reposicao = next(x for x in out["esteiras"] if x["key"] == "reposicao")
    assert [t["ordem"] for t in reposicao["toques"]] == [1, 2, 3]
    assert [t["dias"] for t in reposicao["toques"]] == [15, 11, 12]
    assert reposicao["acao_final"] == "mark_deal_lost"


@pytest.mark.asyncio
async def test_get_le_parametros_do_banco_e_nao_do_seed():
    sb = _banco()
    e = _esteira("reposicao")
    cfg = _no_do_banco(sb, e["nodes"][0]["id"])["config"]
    cfg.update({"stage_id": "stage-ja-chamado", "pipeline_id": "pipe-joao", "silence_days": 20})
    _no_do_banco(sb, e["nodes"][1]["id"])["config"]["template_name"] = "outro_template"
    sb.dados["campaigns"][0]["channel_id"] = "ch-joao"
    with _com(sb):
        out = await esteiras_router.listar_esteiras()
    reposicao = next(x for x in out["esteiras"] if x["key"] == "reposicao")
    assert reposicao["etapa_id"] == "stage-ja-chamado"
    assert reposicao["funil_id"] == "pipe-joao"
    assert reposicao["toques"][0]["dias"] == 20
    assert reposicao["toques"][0]["template_name"] == "outro_template"


@pytest.mark.asyncio
async def test_get_proposta_usa_relogio_de_etapa_no_primeiro_toque():
    """A proposta conta dias NA ETAPA (stage_days=3); as outras contam silencio."""
    with _com(_banco()):
        out = await esteiras_router.listar_esteiras()
    por_key = {x["key"]: x for x in out["esteiras"]}
    assert por_key["proposta"]["toques"][0]["dias"] == 3
    assert por_key["proposta"]["etapa_key"] == "proposta_enviada"
    assert por_key["proposta"]["acao_final"] == "alert_seller"
    assert por_key["novo_sem_resposta"]["toques"][0]["dias"] == 3


@pytest.mark.asyncio
async def test_get_devolve_campaign_id_para_o_link_do_builder():
    """A tela linka '/campanhas/cadencias/{campaign_id}'. Sem o id ela teria de achar a
    campanha por (nome, env_tag) — e renomear no builder e exatamente o que a decisao
    do dono ('eles editam sozinhos') convida a acontecer."""
    with _com(_banco()):
        out = await esteiras_router.listar_esteiras()
    assert {x["key"]: x["campaign_id"] for x in out["esteiras"]} == {
        e["key"]: e["campaign_id"] for e in seed.ESTEIRAS}


@pytest.mark.asyncio
async def test_get_devolve_a_config_do_gatilho():
    """A tela escreve a regra em portugues a partir dela. Sem `last_speaker`, as duas
    esteiras de 'Novo' ficam visualmente identicas — e o falante e a UNICA diferenca."""
    with _com(_banco()):
        out = await esteiras_router.listar_esteiras()
    por_key = {x["key"]: x["gatilho"] for x in out["esteiras"]}
    assert por_key["novo_sem_resposta"]["last_speaker"] == "lead"
    assert por_key["novo_reengajamento"]["last_speaker"] == "nos"
    assert por_key["reposicao"]["silence_days"] == 15
    assert por_key["proposta"]["stage_days"] == 3
    assert por_key["proposta"]["stage_key"] == "proposta_enviada"


@pytest.mark.asyncio
async def test_get_gatilho_reflete_o_banco():
    sb = _banco()
    _no_do_banco(sb, _esteira("reposicao")["nodes"][0]["id"])["config"].update(
        {"last_speaker": "lead", "silence_days": 21})
    with _com(sb):
        out = await esteiras_router.listar_esteiras()
    gatilho = next(x["gatilho"] for x in out["esteiras"] if x["key"] == "reposicao")
    assert gatilho["last_speaker"] == "lead"
    assert gatilho["silence_days"] == 21


@pytest.mark.asyncio
async def test_get_expoe_o_relogio_do_primeiro_toque():
    """A tela precisa rotular '3 dias NA ETAPA' (proposta) x '3 dias SEM RESPOSTA'."""
    with _com(_banco()):
        out = await esteiras_router.listar_esteiras()
    relogio = {x["key"]: x["relogio"] for x in out["esteiras"]}
    assert relogio["proposta"] == "stage_days"
    assert relogio["reposicao"] == relogio["novo_sem_resposta"] == "silence_days"


@pytest.mark.asyncio
async def test_get_cai_no_seed_quando_o_banco_ainda_nao_tem_os_nos():
    sb = _FakeSB({"campaigns": _linhas_campanhas(), "campaign_nodes": [], "pipeline_stages": []})
    with _com(sb):
        out = await esteiras_router.listar_esteiras()
    reposicao = next(x for x in out["esteiras"] if x["key"] == "reposicao")
    assert len(reposicao["toques"]) == 3
    assert reposicao["etapa_id"] is None


# ── PUT: basico ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_key_desconhecida_da_404():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("nao_existe", {"ativa": True})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_put_liga_e_grava_canal():
    sb = _banco(stages=[{"id": "st-perdido", "key": "fechado_perdido",
                         "pipeline_id": "pipe-joao", "order_index": 9}])
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {
            "ativa": True, "canal_id": "ch-joao", "funil_id": "pipe-joao",
            "etapa_id": "stage-x", "toques": [{"ordem": 1, "dias": 20, "template_name": "t"}],
        })
    assert out["ok"] is True
    campanha = sb.updates("campaigns")
    assert any(p.get("status") == "active" for p, _ in campanha)
    assert any(p.get("channel_id") == "ch-joao" for p, _ in campanha)
    assert all(f.get("id") == _esteira("reposicao")["campaign_id"] for _, f in campanha)


@pytest.mark.asyncio
async def test_put_desliga_grava_draft():
    sb = _banco(status={"reposicao": "active"})
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"ativa": False})
    assert any(p.get("status") == "draft" for p, _ in sb.updates("campaigns"))


@pytest.mark.asyncio
async def test_put_campanha_ausente_no_banco_nao_finge_sucesso():
    """Seed que falhou (ex.: coluna `audience` sem migration) deixa a tela achando
    que gravou enquanto o update nao acha linha nenhuma."""
    from fastapi import HTTPException
    sb = _FakeSB({"campaigns": [], "campaign_nodes": [], "pipeline_stages": []})
    with _com(sb), pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("reposicao", {"ativa": False})
    assert exc.value.status_code == 409
    assert sb.escritas == []


# ── PUT: regra 1 — ligar exige etapa ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_recusa_ligar_sem_etapa_configurada():
    from fastapi import HTTPException
    sb = _banco()
    with _com(sb), pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("reposicao", {"ativa": True})
    assert exc.value.status_code == 400
    assert "etapa" in str(exc.value.detail).lower()
    assert sb.escritas == [], "PUT recusado nao pode gravar nada pela metade"


@pytest.mark.asyncio
async def test_put_aceita_configurar_e_ligar_no_mesmo_corpo():
    """A etapa do corpo vale ANTES da checagem: o usuario configura e liga num clique."""
    sb = _banco()
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {
            "ativa": True, "funil_id": "pipe-joao", "etapa_id": "stage-x"})
    assert any(p.get("status") == "active" for p, _ in sb.updates("campaigns"))
    gatilho = _esteira("reposicao")["nodes"][0]["id"]
    cfg = next(p["config"] for p, f in sb.updates("campaign_nodes") if f.get("id") == gatilho)
    assert cfg["stage_id"] == "stage-x"


@pytest.mark.asyncio
async def test_put_liga_com_etapa_ja_gravada_no_banco():
    sb = _banco()
    _no_do_banco(sb, _esteira("reposicao")["nodes"][0]["id"])["config"]["stage_id"] = "stage-x"
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"ativa": True})
    assert any(p.get("status") == "active" for p, _ in sb.updates("campaigns"))


@pytest.mark.asyncio
async def test_put_liga_proposta_sem_stage_id_porque_o_stage_key_ja_filtra():
    """A regra e 'sem stage_id NEM stage_key'. A proposta nasce com
    stage_key='proposta_enviada', que ja e filtro suficiente na RPC."""
    sb = _banco()
    with _com(sb):
        out = await esteiras_router.gravar_esteira("proposta", {"ativa": True})
    assert out["ok"] is True
    assert any(p.get("status") == "active" for p, _ in sb.updates("campaigns"))


@pytest.mark.asyncio
async def test_put_recusa_ligar_quando_o_corpo_limpa_a_etapa():
    from fastapi import HTTPException
    sb = _banco()
    _no_do_banco(sb, _esteira("reposicao")["nodes"][0]["id"])["config"]["stage_id"] = "stage-x"
    with _com(sb), pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("reposicao", {"ativa": True, "etapa_id": ""})
    assert exc.value.status_code == 400
    assert sb.escritas == []


@pytest.mark.asyncio
async def test_put_desligar_sem_etapa_e_permitido():
    sb = _banco()
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"ativa": False, "funil_id": "pipe-joao"})
    assert any(p.get("status") == "draft" for p, _ in sb.updates("campaigns"))


# ── PUT: regra 2 — etapa de Perdido resolvida pela API ───────────────────────────


def _cfg_da_acao_lost(sb) -> dict | None:
    acao = next(n for n in _esteira("reposicao")["nodes"]
                if n["type"] == "action" and n["config"].get("action_type") == "mark_deal_lost")
    for payload, filtros in sb.updates("campaign_nodes"):
        if filtros.get("id") == acao["id"]:
            return payload["config"]
    return None


@pytest.mark.asyncio
async def test_put_resolve_a_etapa_de_perdido_ao_gravar_o_funil():
    """Sem stage_id o `mark_deal_lost` e no-op silencioso: a esteira faria os tres
    toques e NAO moveria o card — o oposto da decisao do dono."""
    sb = _banco(stages=[
        {"id": "st-ganho", "key": "fechado_ganho", "pipeline_id": "pipe-joao", "order_index": 8},
        {"id": "st-perdido", "key": "fechado_perdido", "pipeline_id": "pipe-joao", "order_index": 9},
    ])
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {"funil_id": "pipe-joao"})
    assert _cfg_da_acao_lost(sb)["stage_id"] == "st-perdido"
    assert out.get("aviso") is None


@pytest.mark.asyncio
async def test_put_aceita_o_vocabulario_de_perdido_do_funil_de_importacao():
    sb = _banco(stages=[{"id": "st-encerrado", "key": "encerrado",
                         "pipeline_id": "pipe-frio", "order_index": 5}])
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"funil_id": "pipe-frio"})
    assert _cfg_da_acao_lost(sb)["stage_id"] == "st-encerrado"


@pytest.mark.asyncio
async def test_put_avisa_em_vez_de_falhar_quando_o_funil_nao_tem_etapa_de_perda():
    sb = _banco(stages=[{"id": "st-novo", "key": "novo", "pipeline_id": "pipe-sem-perdido",
                         "order_index": 1}])
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {"funil_id": "pipe-sem-perdido"})
    assert out["ok"] is True
    assert out.get("aviso")
    assert "perdido" in out["aviso"].lower()
    gatilho = _esteira("reposicao")["nodes"][0]["id"]
    cfg = next(p["config"] for p, f in sb.updates("campaign_nodes") if f.get("id") == gatilho)
    assert cfg["pipeline_id"] == "pipe-sem-perdido", "o resto tem de ser gravado assim mesmo"


@pytest.mark.asyncio
async def test_put_limpa_a_etapa_de_perdido_do_funil_antigo():
    """Trocar de funil deixando o stage_id antigo faria a esteira mover o card para
    uma coluna de OUTRO funil — o card sumiria do Kanban de origem."""
    sb = _banco(stages=[{"id": "st-novo", "key": "novo", "pipeline_id": "pipe-novo",
                         "order_index": 1}])
    e = _esteira("reposicao")
    _no_do_banco(sb, e["nodes"][0]["id"])["config"]["pipeline_id"] = "pipe-antigo"
    acao = next(n for n in e["nodes"] if n["type"] == "action")
    _no_do_banco(sb, acao["id"])["config"]["stage_id"] = "st-perdido-antigo"
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {"funil_id": "pipe-novo"})
    assert out["ok"] is True
    assert out["aviso"]
    assert _cfg_da_acao_lost(sb)["stage_id"] is None


@pytest.mark.asyncio
async def test_put_recusa_etapa_de_gatilho_de_outro_funil():
    """A RPC filtra por etapa E funil: a combinacao errada nao levanta erro nenhum,
    so para de achar card — esteira ligada e muda e pior do que um 400."""
    from fastapi import HTTPException
    sb = _banco(stages=[{"id": "stage-x", "key": "ja_chamado", "pipeline_id": "pipe-outro",
                         "order_index": 2}])
    with _com(sb), pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("reposicao", {
            "funil_id": "pipe-joao", "etapa_id": "stage-x"})
    assert exc.value.status_code == 400
    assert "funil" in str(exc.value.detail).lower()
    assert sb.escritas == []


@pytest.mark.asyncio
async def test_put_aceita_etapa_do_proprio_funil():
    sb = _banco(stages=[{"id": "stage-x", "key": "ja_chamado", "pipeline_id": "pipe-joao",
                         "order_index": 2},
                        {"id": "st-perdido", "key": "perdido", "pipeline_id": "pipe-joao",
                         "order_index": 9}])
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {
            "ativa": True, "funil_id": "pipe-joao", "etapa_id": "stage-x"})
    assert out["ok"] is True
    assert _cfg_da_acao_lost(sb)["stage_id"] == "st-perdido"


@pytest.mark.asyncio
async def test_put_respeita_stage_id_perdido_explicito():
    sb = _banco(stages=[{"id": "st-perdido", "key": "perdido", "pipeline_id": "pipe-joao",
                         "order_index": 9}])
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {
            "funil_id": "pipe-joao", "stage_id_perdido": "st-escolhida-a-mao"})
    assert _cfg_da_acao_lost(sb)["stage_id"] == "st-escolhida-a-mao"


@pytest.mark.asyncio
async def test_put_nao_resolve_perdido_em_esteira_que_nunca_move_o_card():
    sb = _banco(stages=[{"id": "st-perdido", "key": "perdido", "pipeline_id": "pipe-joao",
                         "order_index": 9}])
    with _com(sb):
        await esteiras_router.gravar_esteira("proposta", {"funil_id": "pipe-joao"})
    acoes = [n for n in _esteira("proposta")["nodes"] if n["type"] == "action"]
    ids = {a["id"] for a in acoes}
    for payload, filtros in sb.updates("campaign_nodes"):
        if filtros.get("id") in ids:
            assert "stage_id" not in payload["config"]


# ── PUT: parametros dos toques e nao-destrutividade ──────────────────────────────


@pytest.mark.asyncio
async def test_put_grava_dias_e_template_nos_nos_certos():
    sb = _banco()
    e = _esteira("reposicao")
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {
            "etapa_id": "stage-x",
            "toques": [
                {"ordem": 1, "dias": 20, "template_name": "tpl_um"},
                {"ordem": 2, "dias": 7, "template_name": "tpl_dois"},
                {"ordem": 3, "dias": 9, "template_name": "tpl_tres"},
            ],
        })
    por_id = {f["id"]: p["config"] for p, f in sb.updates("campaign_nodes")}
    assert por_id[e["nodes"][0]["id"]]["silence_days"] == 20   # gatilho
    assert por_id[e["nodes"][1]["id"]]["template_name"] == "tpl_um"   # envio 1
    assert por_id[e["nodes"][2]["id"]]["days"] == 7                   # espera 1
    assert por_id[e["nodes"][3]["id"]]["template_name"] == "tpl_dois"  # envio 2
    assert por_id[e["nodes"][4]["id"]]["days"] == 9                   # espera 2
    assert por_id[e["nodes"][5]["id"]]["template_name"] == "tpl_tres"  # envio 3


@pytest.mark.asyncio
async def test_put_da_proposta_grava_no_relogio_de_etapa():
    sb = _banco()
    with _com(sb):
        await esteiras_router.gravar_esteira("proposta", {
            "toques": [{"ordem": 1, "dias": 4, "template_name": "tpl"}]})
    gatilho = _esteira("proposta")["nodes"][0]["id"]
    cfg = next(p["config"] for p, f in sb.updates("campaign_nodes") if f.get("id") == gatilho)
    assert cfg["stage_days"] == 4
    assert cfg["silence_days"] == 0


@pytest.mark.asyncio
async def test_put_parcial_nao_apaga_a_configuracao_anterior():
    """`{'ativa': false}` nao pode devolver o gatilho aos defaults do seed."""
    sb = _banco(status={"reposicao": "active"})
    e = _esteira("reposicao")
    _no_do_banco(sb, e["nodes"][0]["id"])["config"].update(
        {"stage_id": "stage-x", "pipeline_id": "pipe-joao", "silence_days": 20})
    _no_do_banco(sb, e["nodes"][1]["id"])["config"]["template_name"] = "tpl_editado"
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"ativa": False})
    for payload, filtros in sb.updates("campaign_nodes"):
        if filtros.get("id") == e["nodes"][0]["id"]:
            assert payload["config"]["stage_id"] == "stage-x"
            assert payload["config"]["pipeline_id"] == "pipe-joao"
            assert payload["config"]["silence_days"] == 20
        if filtros.get("id") == e["nodes"][1]["id"]:
            assert payload["config"]["template_name"] == "tpl_editado"


@pytest.mark.asyncio
async def test_put_preserva_on_reply_cancel_do_gatilho():
    """on_reply='pause' (o default do motor) deixaria o lead inelegivel para sempre."""
    sb = _banco()
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {"etapa_id": "stage-x"})
    gatilho = _esteira("reposicao")["nodes"][0]["id"]
    cfg = next(p["config"] for p, f in sb.updates("campaign_nodes") if f.get("id") == gatilho)
    assert cfg["on_reply"] == "cancel"
    assert cfg["trigger_type"] == "deal_stage_stagnation"


@pytest.mark.asyncio
async def test_put_nao_altera_a_topologia():
    sb = _banco()
    with _com(sb):
        await esteiras_router.gravar_esteira("reposicao", {
            "etapa_id": "stage-x", "funil_id": "pipe-joao",
            "toques": [{"ordem": 1, "dias": 20, "template_name": "t"}]})
    for tabela, modo, payload, _f in sb.escritas:
        assert modo == "update", "a tela nao insere nem apaga no"
        if tabela == "campaign_nodes":
            assert set(payload) == {"config"}, "so `config` — nunca next_node_id/type"


@pytest.mark.asyncio
async def test_put_ignora_toque_a_mais_do_que_a_esteira_tem():
    """A escrita nao cria no: um corpo com 4 toques numa esteira de 3 nao pode explodir."""
    sb = _banco()
    with _com(sb):
        out = await esteiras_router.gravar_esteira("reposicao", {
            "etapa_id": "stage-x",
            "toques": [{"ordem": i, "dias": 5, "template_name": f"t{i}"} for i in range(1, 5)],
        })
    assert out["ok"] is True
    ids_validos = {n["id"] for n in _esteira("reposicao")["nodes"]}
    assert all(f["id"] in ids_validos for _p, f in sb.updates("campaign_nodes"))


@pytest.mark.asyncio
async def test_put_recusa_dias_invalido():
    from fastapi import HTTPException
    sb = _banco()
    with _com(sb), pytest.raises(HTTPException) as exc:
        await esteiras_router.gravar_esteira("reposicao", {
            "toques": [{"ordem": 1, "dias": -3, "template_name": "t"}]})
    assert exc.value.status_code == 400
    assert sb.escritas == []

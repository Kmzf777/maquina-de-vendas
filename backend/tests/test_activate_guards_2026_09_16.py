"""Guardas de ATIVACAO do builder de campanhas — POST /api/campaigns/{id}/activate.

A validacao em si (`app/campaigns/validation.py`) e pura e ja tem suite propria
(`test_campaign_validation_2026_09_16.py`). O que ESTE arquivo fixa e o que so existe
na fronteira HTTP, e que a funcao pura nao pode provar sozinha:

1. A ROTA CHAMA A VALIDACAO. Antes desta leva ela conferia DUAS coisas — existe gatilho
   e ele tem `next_node_id`. Campanha com template PENDING, com ciclo ou com condicao
   de um ramo so subia para `active` com 200. Quem carregava as outras guardas era a
   aba Esteiras, que vai ser aposentada.
2. VALIDA ANTES DE ESCREVER. Ativacao recusada nao pode deixar a campanha meio ligada:
   `update_campaign` nao e chamado uma unica vez quando ha problema.
3. `{}` E `None` SAO ESTADOS OPOSTOS na consulta a `message_templates`. Mapa vazio e uma
   RESPOSTA ("a Meta nao conhece nenhum desses nomes") e REPROVA; `None` e "a consulta
   falhou" e faz fail-open SO na regra de template. Os dois testes que separam isso
   (`test_mapa_vazio_...` e `test_falha_na_consulta_...`) sao o par que pega o atalho
   `if not templates: templates = None` — com ele, timeout do Supabase vira ativacao
   aprovada em silencio, que e exatamente a falha que a camada existe para impedir.
4. O 400 CARREGA `no_id`/`codigo`/`mensagem`. A tela destaca o no culpado no canvas; um
   400 com string solta nao da para desenhar.

Por que template nao aprovado e a regra mais cara: ele NAO impede a inscricao, so o
envio. A campanha inscreve o lead, nao manda nada e mesmo assim caminha ate a acao
final — registrando "nao teve resposta" para quem nunca foi contatado.
"""
import contextlib
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.campaigns.system_cadence import VALERIA_CADENCE_CAMPAIGN_ID
from app.main import app

client = TestClient(app)

CAMP = "44444444-4444-4444-8444-444444444444"
_URL = f"/api/campaigns/{CAMP}/activate"

FUNIL = "11111111-1111-4111-8111-111111111111"
ETAPA = "22222222-2222-4222-8222-222222222222"
CANAL = "33333333-3333-4333-8333-333333333333"

T1 = "joao_conversa_atacado_t1"
T2 = "joao_conversa_atacado_t2"

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
    """Uma linha de `campaign_nodes` como `list_nodes` (PostgREST) devolve."""
    return {
        "id": nid, "campaign_id": CAMP, "type": tipo, "config": dict(config or {}),
        "next_node_id": prox, "yes_node_id": sim, "no_node_id": nao,
    }


def _grafo():
    """A mesma cadencia valida da suite da validacao: gatilho -> toque 1 -> espera ->
    "respondeu?"; SIM -> fim, NAO -> toque 2 -> fim (losango, sem ciclo)."""
    campanha = {"id": CAMP, "name": "Reposicao — Joao", "status": "draft",
                "channel_id": CANAL}
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


def _por_id(nos, nid):
    return next(n for n in nos if n["id"] == nid)


def _linhas(*nomes, status="APPROVED"):
    """Linhas de `message_templates` como o PostgREST devolve (name, status)."""
    return [{"name": nome, "status": status} for nome in nomes]


class _BancoDeTemplates:
    """So o suficiente de `sb.table(...).select(...).in_(...).execute().data`.

    Guarda o que foi consultado: e assim que os testes provam que a rota NAO bate no
    banco quando nao ha nenhum no `send` (nada a conferir) — caso que tem de virar
    `{}`, nao `None`.
    """

    def __init__(self, linhas=None, erro=None):
        self._linhas = list(linhas or [])
        self._erro = erro
        self.tabelas: list[str] = []
        self.nomes_consultados: list[list[str]] = []

    def table(self, nome):
        self.tabelas.append(nome)
        return self

    def select(self, *_a, **_k):
        return self

    def in_(self, _coluna, valores):
        self.nomes_consultados.append(list(valores))
        return self

    def execute(self):
        if self._erro is not None:
            raise self._erro
        return SimpleNamespace(data=list(self._linhas))


@contextlib.contextmanager
def _rota(campanha, nos, *, linhas=None, erro=None):
    """Isola a rota do banco: campanha, nos e `message_templates` vem dos mocks.

    Patch em `app.db.supabase.get_supabase` (e nao em `app.campaigns.router.
    get_supabase`) porque a rota importa o cliente DENTRO da funcao — o mesmo estilo de
    import local que `_reject_system_campaign` ja usa no modulo.
    """
    banco = _BancoDeTemplates(linhas, erro)
    with patch("app.campaigns.router.get_campaign", return_value=campanha), \
         patch("app.campaigns.router.list_nodes", return_value=nos), \
         patch("app.campaigns.router.update_campaign") as update, \
         patch("app.db.supabase.get_supabase", return_value=banco):
        yield SimpleNamespace(banco=banco, update=update)


def _problemas(resposta):
    return resposta.json()["detail"]["problemas"]


def _codigos(resposta):
    return sorted(p["codigo"] for p in _problemas(resposta))


def _texto(resposta):
    return " ".join(p["mensagem"] for p in _problemas(resposta))


# -- O caminho feliz -------------------------------------------------------------


def test_campanha_valida_com_templates_aprovados_ativa():
    campanha, nos = _grafo()

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "active"}
    mocks.update.assert_called_once_with(CAMP, status="active")


def test_consulta_leva_so_os_nomes_dos_nos_send():
    """O mapa que a validacao recebe e nome -> status CRU; quem monta o `in_` e a rota.
    Consultar nome de um no que NAO e `send` mascararia a regra (a validacao so cobra
    template em `send`) e travaria a ativacao por um template que nao vai ser usado."""
    campanha, nos = _grafo()

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 200, r.text
    assert mocks.banco.tabelas == ["message_templates"]
    assert mocks.banco.nomes_consultados == [sorted([T1, T2])]


def test_campanha_sem_no_send_nao_consulta_message_templates():
    """Sem nenhum `send` nao ha template a conferir. Isso e `{}` (nada a conferir), nao
    falha de consulta: a campanha ativa e o banco nem e tocado."""
    campanha = {"id": CAMP, "name": "So move card", "status": "draft",
                "channel_id": CANAL}
    nos = [
        _no("gat", "trigger", _GATILHO_OK, prox="acao"),
        _no("acao", "action", {"action_type": "move_deal_stage", "stage_id": ETAPA},
            prox="fim"),
        _no("fim", "end", {}),
    ]

    with _rota(campanha, nos) as mocks:
        r = client.post(_URL)

    assert r.status_code == 200, r.text
    assert mocks.banco.tabelas == [], "consultou o banco sem ter template a conferir"
    mocks.update.assert_called_once_with(CAMP, status="active")


def test_espelho_por_canal_com_um_aprovado_basta():
    """`message_templates` tem uma linha-espelho POR CANAL (os canais compartilham a
    mesma WABA) e o sync tem buracos. Ficar com a ULTIMA linha que veio reprovaria um
    template que a Meta aprovou — mesmo criterio do `esteiras_router._nao_aprovados`."""
    campanha, nos = _grafo()
    linhas = [
        {"name": T1, "status": "APPROVED"},
        {"name": T2, "status": "APPROVED"},
        {"name": T2, "status": "PENDING"},   # espelho desatualizado de outro canal
    ]

    with _rota(campanha, nos, linhas=linhas) as mocks:
        r = client.post(_URL)

    assert r.status_code == 200, r.text
    mocks.update.assert_called_once_with(CAMP, status="active")


# -- Template: a regra mais cara -------------------------------------------------


def test_template_pendente_bloqueia_e_a_resposta_diz_nome_e_status():
    """PENDING existe e esta certo — a acao e ESPERAR. A mensagem tem de trazer o NOME
    (qual abrir na Meta) e o STATUS (o que fazer com ele)."""
    campanha, nos = _grafo()

    with _rota(campanha, nos,
               linhas=_linhas(T1) + _linhas(T2, status="PENDING")) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["template_nao_aprovado"]
    assert T2 in _texto(r)
    assert "PENDING" in _texto(r)
    mocks.update.assert_not_called()


def test_template_que_nao_existe_em_message_templates_bloqueia_dizendo_que_nao_existe():
    """Ausente da tabela nao e "nao aprovado": e "nunca foi submetido". A acao e CRIAR —
    e o estado inicial deste projeto, em que os templates `esteira_*` do seed nunca
    foram enviados para a Meta."""
    campanha, nos = _grafo()

    with _rota(campanha, nos, linhas=_linhas(T1)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["template_nao_aprovado"]
    assert T2 in _texto(r)
    assert "NÃO EXISTE" in _texto(r)
    mocks.update.assert_not_called()


def test_mapa_vazio_de_templates_reprova_em_vez_de_liberar():
    """A metade `{}` da armadilha: o banco RESPONDEU, e a resposta foi "a Meta nao
    conhece nenhum desses nomes". Isso reprova os dois toques. Tratar o vazio como
    falha de consulta (fail-open) deixaria passar exatamente a campanha que nao envia
    nada — e o par deste teste e `test_falha_na_consulta_...`, que exige o contrario."""
    campanha, nos = _grafo()

    with _rota(campanha, nos, linhas=[]) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["template_nao_aprovado", "template_nao_aprovado"]
    assert {p["no_id"] for p in _problemas(r)} == {"t1", "t2"}
    mocks.update.assert_not_called()


def test_falha_na_consulta_de_templates_nao_bloqueia_a_ativacao():
    """A metade `None`: a consulta LEVANTOU. Travar a ativacao inteira por uma oscilacao
    do Supabase e pior do que o risco que a guarda cobre (a tela ja filtra o select por
    aprovados) — mesmo criterio do `esteiras_router._nao_aprovados`. Aqui o T2 nem
    sequer existiria na Meta: e a prova de que a regra foi PULADA, nao satisfeita."""
    campanha, nos = _grafo()
    _por_id(nos, "t2")["config"]["template_name"] = "template_que_nunca_foi_submetido"

    with _rota(campanha, nos, erro=RuntimeError("timeout no Supabase")) as mocks:
        r = client.post(_URL)

    assert r.status_code == 200, r.text
    mocks.update.assert_called_once_with(CAMP, status="active")


def test_falha_na_consulta_de_templates_nao_perdoa_os_outros_problemas():
    """O fail-open e de UMA regra, nao anistia geral: grafo quebrado continua reprovado
    com o banco fora do ar."""
    campanha, nos = _grafo()
    _por_id(nos, "t2")["config"]["template_name"] = "template_que_nunca_foi_submetido"
    _por_id(nos, "cond")["yes_node_id"] = None   # violacao de OUTRA regra

    with _rota(campanha, nos, erro=RuntimeError("timeout no Supabase")) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["condicao_incompleta"]
    mocks.update.assert_not_called()


# -- As outras guardas que a rota nao tinha --------------------------------------


def test_gatilho_sem_stage_id_e_sem_stage_key_bloqueia():
    """Campo obrigatorio na pratica: `stage_id` e `stage_key` sao opcionais SOZINHOS,
    mas a RPC `get_deals_stage_stagnant` e fail-closed com os dois nulos — a campanha
    liga e nunca encontra card nenhum (no registro isso e o grupo `requer_um_de`)."""
    campanha, nos = _grafo()
    _por_id(nos, "gat")["config"] = {"trigger_type": "deal_stage_stagnation",
                                     "pipeline_id": FUNIL}

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["requer_um_de"]
    assert _problemas(r)[0]["no_id"] == "gat"
    mocks.update.assert_not_called()


def test_no_de_envio_sem_template_name_bloqueia():
    """`worker._execute_send_node` faz `cfg["template_name"]` — acesso direto: nome
    vazio levanta KeyError e a matricula entra em retry."""
    campanha, nos = _grafo()
    _por_id(nos, "t1")["config"]["template_name"] = ""

    with _rota(campanha, nos, linhas=_linhas(T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert _codigos(r) == ["campo_obrigatorio"]
    assert "template_name" in _texto(r)
    mocks.update.assert_not_called()


def test_grafo_com_ciclo_bloqueia():
    """A matricula repete o trecho para sempre: o lead recebe o mesmo toque de novo e de
    novo e a campanha nunca termina."""
    campanha, nos = _grafo()
    _por_id(nos, "t2")["next_node_id"] = "t1"   # volta para o toque 1

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert "ciclo" in _codigos(r)
    mocks.update.assert_not_called()


def test_condicao_com_um_ramo_so_bloqueia():
    """`engine._execute_condition` faz `yes_node_id if result else no_node_id` e, com
    nulo, chama `_complete()`: metade das matriculas morre no meio do fluxo, marcada
    como concluida."""
    campanha, nos = _grafo()
    _por_id(nos, "cond")["no_node_id"] = None

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert "condicao_incompleta" in _codigos(r)
    mocks.update.assert_not_called()


def test_detalhe_do_400_traz_no_id_codigo_e_mensagem_de_cada_problema():
    """Contrato com a tela: ela destaca o no culpado no CANVAS e agrupa por codigo. Um
    400 com string solta obrigaria o frontend a adivinhar de qual no se trata."""
    campanha, nos = _grafo()
    _por_id(nos, "cond")["no_node_id"] = None
    _por_id(nos, "t1")["config"]["template_name"] = ""

    with _rota(campanha, nos, linhas=_linhas(T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    problemas = _problemas(r)
    assert len(problemas) >= 2
    for p in problemas:
        assert set(p.keys()) == {"no_id", "codigo", "mensagem"}, p
        assert p["mensagem"].strip(), p
    assert {"campo_obrigatorio", "condicao_incompleta"} <= set(_codigos(r))
    mocks.update.assert_not_called()


# -- O que ja valia antes desta leva ---------------------------------------------


def test_campanha_de_sistema_continua_409():
    """O espelho do motor de follow-up e somente-leitura: ativa-lo faria o automation
    engine DUPLICAR os toques que o worker de follow-up ja envia. O 409 vem ANTES de
    tudo — nem a campanha e lida."""
    campanha, nos = _grafo()

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(f"/api/campaigns/{VALERIA_CADENCE_CAMPAIGN_ID}/activate")

    assert r.status_code == 409, r.text
    mocks.update.assert_not_called()
    assert mocks.banco.tabelas == []


def test_campanha_inexistente_continua_404():
    with patch("app.campaigns.router.get_campaign", return_value=None), \
         patch("app.campaigns.router.update_campaign") as update:
        r = client.post(_URL)

    assert r.status_code == 404, r.text
    update.assert_not_called()


def test_quando_reprova_nada_e_escrito():
    """Validar ANTES de escrever. Se a validacao rodasse depois do `update_campaign`, a
    campanha ficaria `active` no banco com a tela mostrando erro — e o motor comecaria
    a matricular."""
    campanha, nos = _grafo()
    _por_id(nos, "cond")["yes_node_id"] = None

    with _rota(campanha, nos, linhas=_linhas(T1, T2)) as mocks:
        r = client.post(_URL)

    assert r.status_code == 400, r.text
    assert mocks.update.call_count == 0, (
        "ativacao recusada gravou status na campanha — ela fica meio ligada")
    assert campanha["status"] == "draft"

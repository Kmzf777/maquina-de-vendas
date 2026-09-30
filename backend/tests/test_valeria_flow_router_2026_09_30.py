"""As cinco rotas de `/api/valeria-flow` — a fronteira HTTP do modal de /campanhas.

O que estes testes seguram, em ordem de importância:

1. **A FUSÃO É DO SERVIDOR.** O `GET` devolve registry + overrides já mesclados. Se
   a tela mesclasse, existiriam duas implementações da regra de default — a classe
   de bug que `app/campaigns/node_registry.py` documenta no seu cabeçalho (tela
   grava uma chave, motor lê outra coisa no mesmo nome). Por isso os testes de `GET`
   comparam contra `valeria_content.aplicar`, nunca contra texto digitado aqui.

2. **`destino` é exibido e não tem caminho de escrita.** O grafo é código. O teste
   não se contenta com "o payload de PUT ignora `destino`": ele confere que o MODELO
   do corpo do PUT não declara o campo, que é a razão estrutural de o payload não
   ter onde pousar (mesmo argumento do docstring de `valeria_content.aplicar`).

3. **`rotulos_antigos` acumula.** Quem recebeu a tela ANTIGA e toca nela depois manda
   o rótulo velho; `valeria_engine._casar` usa esse histórico para não perder o
   clique. Sobrescrever em vez de acrescentar perderia o lead por causa de uma edição
   de copy — então o teste grava duas vezes e exige as DUAS entradas.

4. **"Ativar" nunca edita perfil existente.** `runner.py` registra que o canal do
   João (`a3a607b1`) já aponta para o MESMO `agent_profile_id` do canal da ValerIA
   (`674beb13`, verificado em produção 09/09): virar o `kind` daquele perfil
   transformaria o número do vendedor em robô. O teste exige zero `update` e zero
   `delete` em `agent_profiles`.

5. **O INSERT do perfil só usa colunas que a tabela tem.** E a lista de colunas não
   é digitada aqui: sai do TEXTO das migrations (`007_multi_channel.sql`,
   `009b_multi_agent_schema.sql`, `20260820_button_flow_agent.sql`,
   `20260929_valeria_botoes.sql`). Coluna inventada no insert é 400 do PostgREST em
   produção, e nenhum teste com banco de mentira pegaria isso.

Sem banco: `valeria_flow_content`, `agent_profiles` e `channels` vêm do `_Banco`
deste arquivo. A migration `20260929_valeria_botoes.sql` NÃO está aplicada em
nenhum banco — testar contra cliente real aqui seria testar o PGRST205.

Autenticação: o router é `Depends(require_role(["admin"]))`, e `require_role` devolve
uma CLOSURE NOVA a cada chamada — não há como recriar a mesma referência aqui para
usar em `app.dependency_overrides`. Por isso o router expõe a dependência resolvida em
`valeria_flow_router.EXIGIR_ADMIN`, e é essa referência que os testes sobrepõem. O
teste `test_rotas_exigem_admin_sem_override` roda SEM a sobreposição para provar que a
guarda está de fato pendurada no router (um override que nunca foi necessário seria um
teste verde por cima de uma rota aberta).
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_flow_router as rotas
from app.button_flow import valeria_registry as reg
from app.main import app

_URL = "/api/valeria-flow"
_MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


# ═══════════════════════════════════════════════════════════════════════════════
# O banco de mentira
# ═══════════════════════════════════════════════════════════════════════════════
class _Consulta:
    """O suficiente de `sb.table(t).select().eq().limit().execute().data` e das
    escritas (`insert`/`upsert`/`update`/`delete`) que as rotas fazem."""

    def __init__(self, banco, tabela):
        self._banco = banco
        self._tabela = tabela
        self._filtros: list[tuple[str, object]] = []
        self._acao = "select"
        self._payload = None

    # leitura
    def select(self, *_a, **_k):
        self._acao = "select"
        return self

    def eq(self, coluna, valor):
        self._filtros.append((coluna, valor))
        return self

    def limit(self, _n):
        return self

    def order(self, *_a, **_k):
        return self

    # escrita
    def insert(self, payload):
        self._acao = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, **_k):
        self._acao = "upsert"
        self._payload = payload
        return self

    def update(self, payload):
        self._acao = "update"
        self._payload = payload
        return self

    def delete(self):
        self._acao = "delete"
        return self

    # ──
    def _casa(self, linha):
        return all(linha.get(coluna) == valor for coluna, valor in self._filtros)

    def execute(self):
        erro = self._banco.erros.get(self._tabela)
        if erro is not None:
            raise erro

        linhas = self._banco.tabelas.setdefault(self._tabela, [])
        self._banco.registro.append((self._tabela, self._acao, self._payload))

        if self._acao == "select":
            return SimpleNamespace(data=[dict(l) for l in linhas if self._casa(l)])

        if self._acao == "insert":
            nova = dict(self._payload)
            nova.setdefault("id", f"id-{len(linhas) + 1}")
            linhas.append(nova)
            return SimpleNamespace(data=[dict(nova)])

        if self._acao == "upsert":
            nova = dict(self._payload)
            chave = (nova.get("flow_id"), nova.get("node_id"))
            for i, linha in enumerate(linhas):
                if (linha.get("flow_id"), linha.get("node_id")) == chave:
                    nova.setdefault("id", linha.get("id"))
                    linhas[i] = nova
                    return SimpleNamespace(data=[dict(nova)])
            nova.setdefault("id", f"id-{len(linhas) + 1}")
            linhas.append(nova)
            return SimpleNamespace(data=[dict(nova)])

        if self._acao == "update":
            tocadas = []
            for linha in linhas:
                if self._casa(linha):
                    linha.update(self._payload)
                    tocadas.append(dict(linha))
            return SimpleNamespace(data=tocadas)

        if self._acao == "delete":
            apagadas = [dict(l) for l in linhas if self._casa(l)]
            self._banco.tabelas[self._tabela] = [l for l in linhas if not self._casa(l)]
            return SimpleNamespace(data=apagadas)

        raise AssertionError(f"ação não suportada: {self._acao}")


class _Banco:
    def __init__(self, **tabelas):
        self.tabelas: dict[str, list[dict]] = {k: [dict(l) for l in v] for k, v in tabelas.items()}
        self.erros: dict[str, Exception] = {}
        self.registro: list[tuple[str, str, object]] = []

    def table(self, nome):
        return _Consulta(self, nome)

    # ── leitura do registro, para os asserts ──
    def escritas(self, tabela=None):
        return [r for r in self.registro
                if r[1] != "select" and (tabela is None or r[0] == tabela)]

    def payload_de(self, tabela, acao):
        for t, a, payload in self.registro:
            if t == tabela and a == acao:
                return payload
        return None

    def linhas(self, tabela):
        return [dict(l) for l in self.tabelas.get(tabela, [])]


def _linha(node_id, *, corpo=None, rotulos=None, antigos=None):
    """Uma linha de `valeria_flow_content` como o PostgREST devolve."""
    return {
        "id": f"row-{node_id}",
        "flow_id": reg.FLOW_ID,
        "node_id": node_id,
        "corpo": corpo,
        "rotulos": rotulos,
        "rotulos_antigos": antigos if antigos is not None else [],
    }


@pytest.fixture
def cliente():
    """TestClient com a guarda de admin sobreposta (ver o docstring do módulo)."""
    app.dependency_overrides[rotas.EXIGIR_ADMIN] = lambda: "admin"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(rotas.EXIGIR_ADMIN, None)


@pytest.fixture
def banco(monkeypatch):
    """Um `_Banco` vazio ligado nos DOIS pontos de leitura do cliente.

    `valeria_content` faz `from app.db.supabase import get_supabase` no topo, então
    o nome vive no módulo dele — patch em `app.db.supabase.get_supabase` não o
    alcançaria (é o mesmo cuidado que `test_valeria_content_2026_09_29.py` toma).
    """
    b = _Banco(valeria_flow_content=[], agent_profiles=[], channels=[])
    monkeypatch.setattr(conteudo, "get_supabase", lambda: b)
    monkeypatch.setattr(rotas, "get_supabase", lambda: b)
    return b


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/valeria-flow
# ═══════════════════════════════════════════════════════════════════════════════
def _no_do_payload(corpo_json, node_id):
    return next(n for n in corpo_json["nos"] if n["id"] == node_id)


def test_get_traz_todo_no_e_todo_terminal_do_registry(cliente, banco):
    corpo = cliente.get(_URL).json()
    assert {n["id"] for n in corpo["nos"]} == set(reg.NOS)
    assert {t["id"] for t in corpo["terminais"]} == set(reg.TERMINAIS)
    assert corpo["flow_id"] == reg.FLOW_ID


def test_get_devolve_override_aplicado_e_no_intocado_no_default(cliente, banco):
    """A tela nunca mescla: quem funde é o servidor, com `valeria_content.aplicar`."""
    banco.tabelas["valeria_flow_content"] = [
        _linha("N1", corpo="qual o seu segmento?", rotulos={"cafeteria": "Sou cafeteria"}),
    ]
    corpo = cliente.get(_URL).json()

    n1 = _no_do_payload(corpo, "N1")
    assert n1["corpo"] == "qual o seu segmento?"
    por_id = {b["id"]: b["rotulo"] for b in n1["botoes"]}
    assert por_id["cafeteria"] == "Sou cafeteria"
    # id ausente no override mantém o default — a regra é de `aplicar`, não daqui
    assert por_id["loja"] == reg.NOS["N1"].botoes[1].rotulo

    n2 = _no_do_payload(corpo, "N2")
    assert n2["corpo"] == reg.NOS["N2"].corpo
    assert [b["rotulo"] for b in n2["botoes"]] == [b.rotulo for b in reg.NOS["N2"].botoes]


def test_get_traz_o_default_do_registry_ao_lado_do_valor_atual(cliente, banco):
    """A tela precisa do default para oferecer "restaurar o texto original"."""
    banco.tabelas["valeria_flow_content"] = [_linha("N1", corpo="outro corpo")]
    n1 = _no_do_payload(cliente.get(_URL).json(), "N1")
    assert n1["corpo"] == "outro corpo"
    assert n1["corpo_default"] == reg.NOS["N1"].corpo


def test_get_marca_editado_so_onde_ha_override(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [
        _linha("N1", corpo="editado"),
        _linha("T_HANDOFF", corpo="já chamei o João"),
    ]
    corpo = cliente.get(_URL).json()

    assert _no_do_payload(corpo, "N1")["editado"] is True
    assert _no_do_payload(corpo, "N2")["editado"] is False
    por_id = {t["id"]: t for t in corpo["terminais"]}
    assert por_id["T_HANDOFF"]["editado"] is True
    assert por_id["T_ADIAR"]["editado"] is False
    assert corpo["nudge"]["editado"] is False
    assert corpo["rotulo_lista"]["editado"] is False


def test_get_marca_editado_por_botao(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha("N1", rotulos={"cafeteria": "Sou cafeteria"})]
    n1 = _no_do_payload(cliente.get(_URL).json(), "N1")
    por_id = {b["id"]: b for b in n1["botoes"]}
    assert por_id["cafeteria"]["editado"] is True
    assert por_id["loja"]["editado"] is False
    assert n1["editado"] is True, "rótulo editado também acende o nó"


def test_get_expoe_o_destino_de_todo_botao(cliente, banco):
    """`→ N2` na tela: o editor entende o efeito do botão sem poder quebrar o grafo."""
    corpo = cliente.get(_URL).json()
    vistos = 0
    for no in corpo["nos"]:
        declarado = {b.id: b.destino for b in reg.NOS[no["id"]].botoes}
        for botao in no["botoes"]:
            assert botao["destino"] == declarado[botao["id"]]
            vistos += 1
    assert vistos == sum(len(n.botoes) for n in reg.NOS.values()) > 0


def test_o_corpo_do_put_nao_declara_destino_nem_grava(cliente, banco):
    """A razão ESTRUTURAL de `destino` ser só-leitura: não existe campo para ele.

    Um teste que só conferisse "o PUT ignorou o `destino` que mandei" passaria
    igual num dia em que alguém acrescentasse o campo e esquecesse de ligá-lo.
    """
    campos = set(rotas.ConteudoUpdate.model_fields)
    assert campos == {"corpo", "rotulos"}
    assert "destino" not in campos and "grava" not in campos


def test_get_traz_o_nudge_e_o_rotulo_de_lista_com_os_valores_atuais(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [
        _linha(reg.CHAVE_NUDGE, corpo="toca numa das opções"),
        _linha(reg.CHAVE_ROTULO_LISTA, corpo="Escolher"),
    ]
    corpo = cliente.get(_URL).json()

    assert corpo["nudge"]["chave"] == reg.CHAVE_NUDGE
    assert corpo["nudge"]["corpo"] == "toca numa das opções"
    assert corpo["nudge"]["corpo_default"] == reg.CORPO_NUDGE
    assert corpo["nudge"]["editado"] is True

    assert corpo["rotulo_lista"]["chave"] == reg.CHAVE_ROTULO_LISTA
    assert corpo["rotulo_lista"]["corpo"] == "Escolher"
    assert corpo["rotulo_lista"]["corpo_default"] == reg.ROTULO_BOTAO_LISTA
    assert corpo["rotulo_lista"]["limite"] == reg.LIMITE_ROTULO_BOTAO


def test_get_traz_o_nudge_e_o_rotulo_de_lista_nos_defaults_sem_override(cliente, banco):
    corpo = cliente.get(_URL).json()
    assert corpo["nudge"]["corpo"] == reg.CORPO_NUDGE
    assert corpo["rotulo_lista"]["corpo"] == reg.ROTULO_BOTAO_LISTA


def test_get_sobrevive_a_migration_pendente(cliente, banco):
    """`carregar` é fail-open; a tela tem de abrir nos defaults, não em 500."""
    banco.erros["valeria_flow_content"] = RuntimeError(
        "PGRST205: relation valeria_flow_content does not exist"
    )
    resposta = cliente.get(_URL)
    assert resposta.status_code == 200
    assert _no_do_payload(resposta.json(), "N1")["corpo"] == reg.NOS["N1"].corpo


def test_get_expoe_os_limites_da_meta(cliente, banco):
    limites = cliente.get(_URL).json()["limites"]
    assert limites["rotulo_botao"] == reg.LIMITE_ROTULO_BOTAO
    assert limites["titulo_lista"] == reg.LIMITE_TITULO_LISTA
    assert limites["max_botoes"] == reg.MAX_BOTOES


def test_get_da_o_limite_de_24_no_botao_de_lista_e_20_no_de_botoes(cliente, banco):
    """O limite é POR TELA (`_limite_de_rotulo`): lista 24, botões 20. A tela mostra
    o contador de caracteres a partir deste número."""
    corpo = cliente.get(_URL).json()
    assert _no_do_payload(corpo, "N0")["botoes"][0]["limite_rotulo"] == reg.LIMITE_TITULO_LISTA
    assert _no_do_payload(corpo, "N1")["botoes"][0]["limite_rotulo"] == reg.LIMITE_ROTULO_BOTAO


# ═══════════════════════════════════════════════════════════════════════════════
# PUT /api/valeria-flow/{node_id}
# ═══════════════════════════════════════════════════════════════════════════════
def test_put_rejeita_rotulo_de_21_caracteres(cliente, banco):
    resposta = cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "U" * 21}})
    assert resposta.status_code == 400
    assert "20" in resposta.json()["detail"]
    assert banco.escritas() == [], "recusa não pode gravar nada"


def test_put_aceita_rotulo_no_limite(cliente, banco):
    assert cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "U" * 20}}).status_code == 200


def test_put_rejeita_corpo_em_branco_em_no(cliente, banco):
    resposta = cliente.put(f"{_URL}/N1", json={"corpo": "   "})
    assert resposta.status_code == 400
    assert resposta.json()["detail"]
    assert banco.escritas() == []


def test_put_em_no_desconhecido_da_404(cliente, banco):
    resposta = cliente.put(f"{_URL}/NAO_EXISTE", json={"corpo": "x"})
    assert resposta.status_code == 404
    assert banco.escritas() == []


def test_put_grava_corpo_e_rotulos(cliente, banco):
    resposta = cliente.put(
        f"{_URL}/N1", json={"corpo": "que tipo de negócio?", "rotulos": {"cafeteria": "Cafeteria ☕"}}
    )
    assert resposta.status_code == 200
    linha = banco.linhas("valeria_flow_content")[0]
    assert linha["flow_id"] == reg.FLOW_ID
    assert linha["node_id"] == "N1"
    assert linha["corpo"] == "que tipo de negócio?"
    assert linha["rotulos"] == {"cafeteria": "Cafeteria ☕"}


def test_put_com_destino_ou_grava_nao_muda_o_registry(cliente, banco):
    antes_destino = reg.NOS["N1"].botoes[0].destino
    antes_grava = reg.NOS["N1"].botoes[0].grava

    resposta = cliente.put(f"{_URL}/N1", json={
        "corpo": "que tipo de negócio?",
        "destino": "T_OPTOUT",
        "grava": [["segment", "hotel"]],
    })
    assert resposta.status_code == 200

    # 1) o registry em memória não se move
    assert reg.NOS["N1"].botoes[0].destino == antes_destino
    assert reg.NOS["N1"].botoes[0].grava == antes_grava
    # 2) nem o banco guarda as chaves — não há coluna nem leitor para elas
    gravado = banco.payload_de("valeria_flow_content", "upsert")
    assert "destino" not in gravado and "grava" not in gravado
    # 3) nem o GET seguinte muda de rota
    n1 = _no_do_payload(cliente.get(_URL).json(), "N1")
    assert n1["botoes"][0]["destino"] == antes_destino


def test_put_move_o_rotulo_substituido_para_rotulos_antigos(cliente, banco):
    """Sem isto, o lead que recebeu a tela antiga e toca depois perde o clique."""
    antigo = reg.NOS["N1"].botoes[0].rotulo
    resposta = cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Sou cafeteria"}})
    assert resposta.status_code == 200

    historico = banco.linhas("valeria_flow_content")[0]["rotulos_antigos"]
    assert any(e["rotulo"] == antigo and e["botao_id"] == "cafeteria" for e in historico), historico
    assert resposta.json()["rotulos_antigos"] == historico


def test_put_acumula_rotulos_antigos_em_vez_de_sobrescrever(cliente, banco):
    original = reg.NOS["N1"].botoes[0].rotulo
    cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Sou cafeteria"}})
    cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Tenho cafeteria"}})

    historico = banco.linhas("valeria_flow_content")[0]["rotulos_antigos"]
    rotulos = [e["rotulo"] for e in historico]
    assert original in rotulos
    assert "Sou cafeteria" in rotulos, "a segunda edição não pode apagar a primeira"
    assert all(e["botao_id"] == "cafeteria" for e in historico)


def test_put_nao_duplica_a_mesma_entrada_no_historico(cliente, banco):
    cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Sou cafeteria"}})
    cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Sou cafeteria"}})
    historico = banco.linhas("valeria_flow_content")[0]["rotulos_antigos"]
    pares = [(e["botao_id"], e["rotulo"]) for e in historico]
    assert len(pares) == len(set(pares)), pares


def test_put_preserva_o_historico_que_ja_estava_no_banco(cliente, banco):
    ja_existia = [{"botao_id": "loja", "rotulo": "Empório"}]
    banco.tabelas["valeria_flow_content"] = [_linha("N1", antigos=list(ja_existia))]
    cliente.put(f"{_URL}/N1", json={"rotulos": {"cafeteria": "Sou cafeteria"}})
    historico = banco.linhas("valeria_flow_content")[0]["rotulos_antigos"]
    assert ja_existia[0] in historico


def test_put_aceita_a_chave_do_nudge(cliente, banco):
    resposta = cliente.put(f"{_URL}/{reg.CHAVE_NUDGE}", json={"corpo": "toca numa das opções 👇"})
    assert resposta.status_code == 200
    linha = banco.linhas("valeria_flow_content")[0]
    assert linha["node_id"] == reg.CHAVE_NUDGE
    assert linha["corpo"] == "toca numa das opções 👇"


def test_put_rejeita_nudge_em_branco(cliente, banco):
    assert cliente.put(f"{_URL}/{reg.CHAVE_NUDGE}", json={"corpo": " "}).status_code == 400


def test_put_aceita_a_chave_do_rotulo_de_lista(cliente, banco):
    resposta = cliente.put(f"{_URL}/{reg.CHAVE_ROTULO_LISTA}", json={"corpo": "Escolher"})
    assert resposta.status_code == 200
    assert banco.linhas("valeria_flow_content")[0]["node_id"] == reg.CHAVE_ROTULO_LISTA


def test_put_rejeita_rotulo_de_lista_acima_de_20(cliente, banco):
    resposta = cliente.put(f"{_URL}/{reg.CHAVE_ROTULO_LISTA}", json={"corpo": "U" * 21})
    assert resposta.status_code == 400
    assert "20" in resposta.json()["detail"]


def test_put_aceita_corpo_de_terminal(cliente, banco):
    resposta = cliente.put(f"{_URL}/T_HANDOFF", json={"corpo": "já chamei o João Brás"})
    assert resposta.status_code == 200
    assert banco.linhas("valeria_flow_content")[0]["node_id"] == "T_HANDOFF"


def test_put_rejeita_rotulo_em_terminal(cliente, banco):
    """`validar` RECUSA em vez de ignorar: terminal não tem botão próprio, e um
    override silencioso ali seria invisível na tela e morto no motor."""
    resposta = cliente.put(f"{_URL}/T_ADIAR", json={"rotulos": {"dias30": "Em 1 mês"}})
    assert resposta.status_code == 400
    assert banco.escritas() == []


@pytest.mark.parametrize("chave", ["__nudge__", "__rotulo_lista__"])
def test_put_rejeita_rotulo_nas_chaves_reservadas(cliente, banco, chave):
    """As reservadas guardam o texto em `corpo`; `rotulos` não seria persistido.

    `validar` volta antes de chegar à checagem de terminal, então sem esta guarda o
    salvamento responderia 200 e não gravaria nada — a tela achando que salvou.
    """
    resposta = cliente.put(f"{_URL}/{chave}", json={"rotulos": {"x": "y"}})
    assert resposta.status_code == 400
    assert banco.escritas() == []


def test_put_sem_nenhum_campo_editavel_e_400(cliente, banco):
    resposta = cliente.put(f"{_URL}/N1", json={"destino": "T_OPTOUT"})
    assert resposta.status_code == 400
    assert banco.escritas() == []


def test_put_nao_grava_quando_a_leitura_do_historico_falha(cliente, banco):
    """Fail-CLOSED aqui, ao contrário do GET: gravar sem ter lido `rotulos_antigos`
    apagaria o histórico da tela antiga em silêncio."""
    banco.erros["valeria_flow_content"] = RuntimeError("PGRST205: relation does not exist")
    resposta = cliente.put(f"{_URL}/N1", json={"corpo": "x"})
    assert resposta.status_code == 503
    assert "20260929" in resposta.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/valeria-flow/{node_id}
# ═══════════════════════════════════════════════════════════════════════════════
def test_delete_restaura_o_default(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [
        _linha("N1", corpo="corpo editado", rotulos={"cafeteria": "Sou cafeteria"}),
    ]
    resposta = cliente.delete(f"{_URL}/N1")
    assert resposta.status_code == 200
    assert resposta.json()["corpo"] == reg.NOS["N1"].corpo
    assert resposta.json()["editado"] is False

    n1 = _no_do_payload(cliente.get(_URL).json(), "N1")
    assert n1["corpo"] == reg.NOS["N1"].corpo
    assert [b["rotulo"] for b in n1["botoes"]] == [b.rotulo for b in reg.NOS["N1"].botoes]
    assert n1["editado"] is False


def test_delete_guarda_o_rotulo_que_estava_no_ar(cliente, banco):
    """Restaurar o default TROCA o rótulo — quem recebeu o editado precisa da rede."""
    banco.tabelas["valeria_flow_content"] = [_linha("N1", rotulos={"cafeteria": "Sou cafeteria"})]
    cliente.delete(f"{_URL}/N1")
    linhas = banco.linhas("valeria_flow_content")
    assert len(linhas) == 1, "a linha fica, só sem override — o histórico não se joga fora"
    assert linhas[0]["corpo"] is None
    assert not linhas[0]["rotulos"]
    assert any(e["rotulo"] == "Sou cafeteria" for e in linhas[0]["rotulos_antigos"])


def test_delete_sem_historico_apaga_a_linha(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha("N1", corpo="só o corpo")]
    cliente.delete(f"{_URL}/N1")
    assert banco.linhas("valeria_flow_content") == []


def test_delete_em_no_desconhecido_da_404(cliente, banco):
    assert cliente.delete(f"{_URL}/NAO_EXISTE").status_code == 404


def test_delete_sem_override_e_idempotente(cliente, banco):
    resposta = cliente.delete(f"{_URL}/N1")
    assert resposta.status_code == 200
    assert resposta.json()["corpo"] == reg.NOS["N1"].corpo


def test_delete_do_nudge_volta_ao_default(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha(reg.CHAVE_NUDGE, corpo="outro")]
    resposta = cliente.delete(f"{_URL}/{reg.CHAVE_NUDGE}")
    assert resposta.status_code == 200
    assert resposta.json()["corpo"] == reg.CORPO_NUDGE
    assert cliente.get(_URL).json()["nudge"]["corpo"] == reg.CORPO_NUDGE


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/valeria-flow/channels
# ═══════════════════════════════════════════════════════════════════════════════
PERFIL_COMPARTILHADO = "674beb13-0000-4000-8000-000000000001"
PERFIL_SO_DELE = "674beb13-0000-4000-8000-000000000002"

CANAL_VALERIA = {
    "id": "674beb13-1111-4111-8111-111111111111", "name": "Valéria",
    "phone": "5534999999999", "mode": "ai", "is_active": True,
    "agent_profile_id": PERFIL_COMPARTILHADO,
    "agent_profiles": {"id": PERFIL_COMPARTILHADO, "name": "ValerIA - Inbound",
                       "kind": "llm", "flow_id": None, "prompt_key": "valeria_inbound"},
}
CANAL_JOAO = {
    "id": "a3a607b1-2222-4222-8222-222222222222", "name": "João",
    "phone": "553491461669", "mode": "human", "is_active": True,
    "agent_profile_id": PERFIL_COMPARTILHADO,
    "agent_profiles": {"id": PERFIL_COMPARTILHADO, "name": "ValerIA - Inbound",
                       "kind": "llm", "flow_id": None, "prompt_key": "valeria_inbound"},
}
CANAL_SOZINHO = {
    "id": "cccccccc-3333-4333-8333-333333333333", "name": "Arthur",
    "phone": "5534900000000", "mode": "ai", "is_active": True,
    "agent_profile_id": PERFIL_SO_DELE,
    "agent_profiles": {"id": PERFIL_SO_DELE, "name": "Exportação",
                       "kind": "llm", "flow_id": None, "prompt_key": "valeria_inbound"},
}


def _por_id(payload):
    return {c["id"]: c for c in payload["canais"]}


def test_channels_sinaliza_perfil_compartilhado(cliente, banco):
    """Os canais 674beb13 (ValerIA) e a3a607b1 (João) apontam para o MESMO perfil em
    produção — verificado 09/09 e registrado em `runner.py`. É esse aviso que impede
    o operador de transformar o número do vendedor em robô."""
    canais = [CANAL_VALERIA, CANAL_JOAO, CANAL_SOZINHO]
    with patch.object(rotas, "list_channels", return_value=canais):
        payload = cliente.get(f"{_URL}/channels").json()

    por_id = _por_id(payload)
    assert por_id[CANAL_VALERIA["id"]]["perfil_compartilhado"] is True
    assert por_id[CANAL_JOAO["id"]]["perfil_compartilhado"] is True
    assert por_id[CANAL_SOZINHO["id"]]["perfil_compartilhado"] is False


def test_channels_nomeia_com_quem_o_perfil_e_compartilhado(cliente, banco):
    with patch.object(rotas, "list_channels", return_value=[CANAL_VALERIA, CANAL_JOAO]):
        por_id = _por_id(cliente.get(f"{_URL}/channels").json())
    assert por_id[CANAL_VALERIA["id"]]["compartilhado_com"] == ["João"]
    assert por_id[CANAL_JOAO["id"]]["compartilhado_com"] == ["Valéria"]


def test_channels_traz_o_perfil_atual_de_cada_canal(cliente, banco):
    with patch.object(rotas, "list_channels", return_value=[CANAL_VALERIA]):
        canal = _por_id(cliente.get(f"{_URL}/channels").json())[CANAL_VALERIA["id"]]
    assert canal["perfil"]["id"] == PERFIL_COMPARTILHADO
    assert canal["perfil"]["kind"] == "llm"
    assert canal["atende_este_fluxo"] is False


def test_channels_marca_o_canal_que_ja_roda_este_fluxo(cliente, banco):
    canal = {**CANAL_VALERIA,
             "agent_profiles": {"id": PERFIL_SO_DELE, "name": "Valéria Botões",
                                "kind": "button_flow", "flow_id": reg.FLOW_ID},
             "agent_profile_id": PERFIL_SO_DELE}
    with patch.object(rotas, "list_channels", return_value=[canal]):
        payload = cliente.get(f"{_URL}/channels").json()
    assert _por_id(payload)[canal["id"]]["atende_este_fluxo"] is True


def test_channels_sem_perfil_nao_vira_compartilhado(cliente, banco):
    """Dois canais com `agent_profile_id` NULL não compartilham nada — agrupar por
    None diria que sim e o aviso apareceria onde não há risco."""
    a = {**CANAL_VALERIA, "agent_profile_id": None, "agent_profiles": None}
    b = {**CANAL_JOAO, "agent_profile_id": None, "agent_profiles": None}
    with patch.object(rotas, "list_channels", return_value=[a, b]):
        payload = cliente.get(f"{_URL}/channels").json()
    for canal in payload["canais"]:
        assert canal["perfil_compartilhado"] is False


def test_channels_expoe_o_kill_switch_do_fluxo(cliente, banco, monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    with patch.object(rotas, "list_channels", return_value=[]):
        assert cliente.get(f"{_URL}/channels").json()["ligado"] is True
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "off")
    with patch.object(rotas, "list_channels", return_value=[]):
        assert cliente.get(f"{_URL}/channels").json()["ligado"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/valeria-flow/activate
# ═══════════════════════════════════════════════════════════════════════════════
def _colunas_de_agent_profiles() -> set[str]:
    """As colunas REAIS de `agent_profiles`, lidas do texto das migrations.

    Não digitadas aqui: coluna inventada no INSERT é 400 do PostgREST em produção, e
    um banco de mentira aceitaria qualquer chave em silêncio. As fontes:
      • `007_multi_channel.sql`  — CREATE TABLE (id, name, model, stages, base_prompt, …)
      • `009b_multi_agent_schema.sql` — ADD COLUMN prompt_key
      • `20260820_button_flow_agent.sql` — ADD COLUMN kind
      • `20260929_valeria_botoes.sql` — ADD COLUMN flow_id
    """
    criacao = (_MIGRATIONS / "007_multi_channel.sql").read_text(encoding="utf-8")
    bloco = re.search(
        r"CREATE TABLE IF NOT EXISTS agent_profiles\s*\((.*?)\n\);",
        criacao, re.S | re.I,
    )
    assert bloco, "bloco de criação de agent_profiles não encontrado"
    colunas = set()
    for linha in bloco.group(1).splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("--"):
            continue
        colunas.add(linha.split()[0].strip(","))

    for arquivo, coluna in (
        ("009b_multi_agent_schema.sql", "prompt_key"),
        ("20260820_button_flow_agent.sql", "kind"),
        ("20260929_valeria_botoes.sql", "flow_id"),
    ):
        sql = (_MIGRATIONS / arquivo).read_text(encoding="utf-8").lower()
        assert f"add column if not exists {coluna}" in sql, f"{coluna} em {arquivo}"
        colunas.add(coluna)
    return colunas


@pytest.fixture
def canal(monkeypatch):
    """`get_channel`/`update_channel` do canal escolhido, sem banco."""
    alvo = dict(CANAL_VALERIA)
    atualizados: list[tuple[str, dict]] = []

    def _update(channel_id, data):
        atualizados.append((channel_id, dict(data)))
        return {**alvo, **data}

    monkeypatch.setattr(rotas, "get_channel", lambda cid: alvo if cid == alvo["id"] else None)
    monkeypatch.setattr(rotas, "update_channel", _update)
    return SimpleNamespace(alvo=alvo, atualizados=atualizados)


def test_activate_sem_canal_e_recusado(cliente, banco, canal):
    assert cliente.post(f"{_URL}/activate", json={}).status_code in (400, 422)
    assert cliente.post(f"{_URL}/activate", json={"channel_id": "  "}).status_code == 400
    assert banco.escritas("agent_profiles") == []
    assert canal.atualizados == []


def test_activate_cria_perfil_e_nao_muta_nenhum_existente(cliente, banco, canal):
    banco.tabelas["agent_profiles"] = [
        {"id": PERFIL_COMPARTILHADO, "name": "ValerIA - Inbound", "kind": "llm",
         "flow_id": None, "prompt_key": "valeria_inbound"},
    ]
    resposta = cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    assert resposta.status_code == 200, resposta.text

    acoes = [(t, a) for t, a, _ in banco.registro if t == "agent_profiles" and a != "select"]
    assert acoes == [("agent_profiles", "insert")], acoes

    ainda_la = next(p for p in banco.linhas("agent_profiles") if p["id"] == PERFIL_COMPARTILHADO)
    assert ainda_la["kind"] == "llm", "o perfil que o João compartilha não pode virar bot"
    assert ainda_la["flow_id"] is None

    novo = banco.payload_de("agent_profiles", "insert")
    assert novo["kind"] == "button_flow"
    assert novo["flow_id"] == reg.FLOW_ID
    assert "id" not in novo, "insert com id sobrescreveria uma linha existente"


def test_activate_insere_so_colunas_que_a_tabela_tem(cliente, banco, canal):
    cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    novo = banco.payload_de("agent_profiles", "insert")
    colunas = _colunas_de_agent_profiles()
    assert set(novo) <= colunas, set(novo) - colunas


def test_activate_preenche_as_colunas_not_null_sem_default_utilizavel(cliente, banco, canal):
    """`stages` e `base_prompt` são NOT NULL; `model` também. Um perfil de botões não
    tem prompt nem etapa — o INSERT manda os vazios EXPLÍCITOS, exatamente como
    `20260820_button_flow_agent.sql` faz para o perfil da Recuperação."""
    cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    novo = banco.payload_de("agent_profiles", "insert")
    assert novo["stages"] == {}
    assert novo["base_prompt"] == ""
    assert novo["model"] == ""
    assert novo["name"]

    precedente = (_MIGRATIONS / "20260820_button_flow_agent.sql").read_text(encoding="utf-8")
    assert "'button_flow'" in precedente and "'{}'::jsonb" in precedente


def test_activate_nao_herda_o_prompt_key_da_valeria_llm(cliente, banco, canal):
    """`prompt_key` é NOT NULL DEFAULT 'valeria_inbound'. Omitir a chave faria o perfil
    de BOTÕES nascer com a persona da ValerIA LLM — e
    `get_profile_id_by_prompt_key('valeria_inbound')` usa `.limit(1)`, então
    `processor.py` poderia resolver o perfil de botões para uma conversa de LLM."""
    cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    novo = banco.payload_de("agent_profiles", "insert")
    assert novo["prompt_key"] not in ("valeria_inbound", "valeria_outbound", "bot_reativacao")
    assert novo["prompt_key"]


def test_activate_aponta_so_o_canal_escolhido_e_limpa_o_cache(cliente, banco, canal):
    with patch.object(rotas, "limpar_cache_de_perfis") as limpar:
        resposta = cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    assert resposta.status_code == 200

    novo_id = banco.linhas("agent_profiles")[0]["id"]
    assert canal.atualizados == [(canal.alvo["id"], {"agent_profile_id": novo_id})]
    limpar.assert_called_once()
    assert resposta.json()["agent_profile_id"] == novo_id
    assert resposta.json()["channel_id"] == canal.alvo["id"]


def test_activate_nomeia_o_perfil_pelo_canal_ou_pelo_pedido(cliente, banco, canal):
    cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    assert canal.alvo["name"] in banco.payload_de("agent_profiles", "insert")["name"]

    banco.registro.clear()
    cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"], "nome": "Bot da entrada"})
    assert banco.payload_de("agent_profiles", "insert")["name"] == "Bot da entrada"


def test_activate_com_canal_inexistente_da_404(cliente, banco, canal):
    resposta = cliente.post(f"{_URL}/activate", json={"channel_id": CANAL_SOZINHO["id"]})
    assert resposta.status_code == 404
    assert banco.escritas("agent_profiles") == []


def test_activate_com_flow_id_ainda_nao_migrado_falha_com_mensagem_clara(cliente, banco, canal):
    """A migration 20260929 NÃO está aplicada em nenhum banco. Sem a coluna `flow_id`
    o perfil novo não pode ser criado — e a spec §10 exige mensagem clara em vez de
    ativar errado (um perfil `button_flow` sem `flow_id` cairia no `recuperacao_v1`,
    que roda no número pessoal do vendedor)."""
    banco.erros["agent_profiles"] = RuntimeError(
        "PGRST204: Could not find the 'flow_id' column of 'agent_profiles'"
    )
    resposta = cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    assert resposta.status_code == 503
    assert "20260929" in resposta.json()["detail"]
    assert canal.atualizados == [], "canal não pode ser apontado para perfil que não nasceu"


# ═══════════════════════════════════════════════════════════════════════════════
# A guarda de admin
# ═══════════════════════════════════════════════════════════════════════════════
def test_router_registrado_no_app():
    """Guarda em NÍVEL DE FONTE, a convenção de `test_bling_router.py` e
    `test_quotes_router.py`: inspecionar `app.main.app.routes` em runtime é frágil a
    poluição de módulos entre testes (foi o que derrubou o deploy em 21/08/2026)."""
    import inspect

    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.button_flow.valeria_flow_router import router as valeria_flow_router" in src
    assert "app.include_router(valeria_flow_router)" in src


def test_router_expoe_exatamente_as_cinco_rotas():
    """Objeto isolado, imune a poluição de módulos. CINCO rotas, nem uma a mais —
    uma sexta rota de escrita seria o caminho por onde `destino` voltaria."""
    declaradas = {(r.path, tuple(sorted(r.methods))) for r in rotas.router.routes}
    assert declaradas == {
        ("/api/valeria-flow", ("GET",)),
        ("/api/valeria-flow/channels", ("GET",)),
        ("/api/valeria-flow/activate", ("POST",)),
        ("/api/valeria-flow/{node_id}", ("PUT",)),
        ("/api/valeria-flow/{node_id}", ("DELETE",)),
    }, declaradas


def test_rota_estatica_declarada_antes_da_parametrizada():
    """`/channels` e `/activate` antes de `/{node_id}`: a armadilha que
    `test_node_schema_endpoint_2026_09_16.py` documenta (o path estático casando como
    parâmetro). Hoje os métodos divergem e salvam a rota; a ordem é a garantia que não
    depende disso."""
    caminhos = [r.path for r in rotas.router.routes]
    assert caminhos.index("/api/valeria-flow/channels") < caminhos.index("/api/valeria-flow/{node_id}")
    assert caminhos.index("/api/valeria-flow/activate") < caminhos.index("/api/valeria-flow/{node_id}")


def test_rotas_exigem_admin_sem_override(banco):
    """SEM a sobreposição da fixture: prova que `require_role` está pendurado no
    router. Sem este caso, um override que nunca fosse necessário deixaria a suíte
    verde por cima de cinco rotas abertas."""
    cru = TestClient(app)
    assert cru.get(_URL).status_code == 401
    assert cru.get(f"{_URL}/channels").status_code == 401
    assert cru.put(f"{_URL}/N1", json={"corpo": "x"}).status_code == 401
    assert cru.delete(f"{_URL}/N1").status_code == 401
    assert cru.post(f"{_URL}/activate", json={"channel_id": "x"}).status_code == 401

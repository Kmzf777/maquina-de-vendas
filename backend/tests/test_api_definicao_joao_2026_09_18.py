# backend/tests/test_api_definicao_joao_2026_09_18.py
"""A API da definição das cadências — GET /api/cadence/definition e PUT /api/cadence/joao.

O que esta suíte trava, em ordem de importância:

1. **A ValerIA não muda uma vírgula.** `followup-board.tsx` lê HOJE quatro chaves no
   TOPO do payload (`touches`, `outbound_nudge`, `min_gap_hours`, `business_window`) e
   renderiza a esteira a partir delas. O João entra como chave NOVA ao lado — se a
   definição dela virasse `{"valeria": {...}, "joao": {...}}`, a tela em produção
   passaria a mostrar "Definição da cadência indisponível" no mesmo deploy, sem erro
   nenhum no log. Os testes de regressão vêm primeiro no arquivo de propósito.

2. **O banco sobrepõe, e o código é a origem.** A migration
   `20260918_followup_joao_config.sql` NÃO está aplicada — logo o GET tem de
   sobreviver a `followup_joao_*` inexistente (PGRST205) caindo nos valores do
   código. Um GET que quebra aqui deixa a aba Follow-up inteira vazia.

3. **A forma da cadência não é editável.** `sequence` fora do que o código declara é
   RECUSADA — é a trava que impede a tela de virar builder de novo (spec §5), e é a
   mesma trava que o CHECK `followup_joao_toque_dentro_da_cadencia` tem do lado do
   banco. Sem ela, um toque 9 em "Em conversa" seria gravado, apareceria na tela e
   seria ignorado em silêncio pelo motor.

4. **Ligar exige template aprovado em TODO toque das DUAS linhas.** É a guarda mais
   cara do projeto, e a razão: template que não envia não impede a MATRÍCULA, só o
   envio — a cadência inscreve o card, não manda nada e caminha até o fim, registrando
   "não teve resposta" para quem nunca foi contatado. "Em atenção" hoje não tem NENHUM
   template (os 24 aprovados cobrem só Novo + Em conversa + Reposição), então ligá-la é
   sempre recusado — e isso é uma declaração, não um bug.

Sem banco na suíte: as duas tabelas de sobreposição e `message_templates` vêm do
`_Banco` deste arquivo, no mesmo estilo do `_BancoDeTemplates` de
`test_activate_guards_2026_09_16.py` (patch em `app.db.supabase.get_supabase`, porque
a API importa o cliente DENTRO da função).
"""
import contextlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.follow_up import cadence_joao as cj
from app.follow_up.api import build_cadence_definition
from app.follow_up.cadence import CADENCE, MIN_GAP, OUTBOUND_NUDGE
from app.main import app

client = TestClient(app)

GET_URL = "/api/cadence/definition"
PUT_URL = "/api/cadence/joao"

ATACADO = cj.LINHA_ATACADO
PRIVATE = cj.LINHA_PRIVATE_LABEL


# ═══════════════════════════════════════════════════════════════════════════════
# O banco de mentira
# ═══════════════════════════════════════════════════════════════════════════════
class _Consulta:
    """O suficiente de `sb.table(x).select(...).eq(...).in_(...).execute().data`."""

    def __init__(self, banco, tabela):
        self._banco = banco
        self._tabela = tabela
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []

    def select(self, *_a, **_k):
        return self

    def eq(self, coluna, valor):
        self._eq.append((coluna, valor))
        return self

    def in_(self, coluna, valores):
        self._in.append((coluna, list(valores)))
        self._banco.nomes_consultados.append(sorted(valores))
        return self

    def limit(self, _n):
        return self

    def upsert(self, linhas, on_conflict=None):
        linhas = linhas if isinstance(linhas, list) else [linhas]
        self._banco.escritas.append(
            {"tabela": self._tabela, "linhas": [dict(x) for x in linhas],
             "on_conflict": on_conflict}
        )
        for nova in linhas:
            chave = on_conflict.split(",") if on_conflict else []
            atual = self._banco.tabelas.setdefault(self._tabela, [])
            for i, antiga in enumerate(atual):
                if all(antiga.get(c) == nova.get(c) for c in chave):
                    atual[i] = dict(nova)
                    break
            else:
                atual.append(dict(nova))
        return self

    def execute(self):
        erro = self._banco.erros.get(self._tabela)
        if erro is not None:
            raise erro
        linhas = list(self._banco.tabelas.get(self._tabela, []))
        for coluna, valor in self._eq:
            linhas = [x for x in linhas if x.get(coluna) == valor]
        for coluna, valores in self._in:
            linhas = [x for x in linhas if x.get(coluna) in valores]
        return SimpleNamespace(data=[dict(x) for x in linhas])


class _Banco:
    def __init__(self, tabelas=None, erros=None):
        self.tabelas: dict[str, list[dict]] = {k: [dict(r) for r in v]
                                               for k, v in (tabelas or {}).items()}
        self.erros: dict[str, Exception] = dict(erros or {})
        self.escritas: list[dict] = []
        self.tabelas_tocadas: list[str] = []
        self.nomes_consultados: list[list[str]] = []

    def table(self, nome):
        self.tabelas_tocadas.append(nome)
        return _Consulta(self, nome)

    # -- leitura conveniente para as asserções --------------------------------
    def escritas_em(self, tabela) -> list[dict]:
        return [linha for e in self.escritas if e["tabela"] == tabela
                for linha in e["linhas"]]


def _toque(cadencia, linha, toque, *, dias=None, template_name=None,
           atualizado_por=None):
    """Uma linha de `followup_joao_toque` como o PostgREST devolve."""
    return {"cadencia": cadencia, "linha": linha, "toque": toque, "dias": dias,
            "template_name": template_name, "atualizado_por": atualizado_por,
            "updated_at": "2026-09-18T12:00:00+00:00"}


def _cad(cadencia, *, gatilho_dias=None, ativa=None, atualizado_por=None):
    """Uma linha de `followup_joao_cadencia`."""
    return {"cadencia": cadencia, "gatilho_dias": gatilho_dias, "ativa": ativa,
            "atualizado_por": atualizado_por,
            "updated_at": "2026-09-18T12:00:00+00:00"}


def _templates(*nomes, status="APPROVED"):
    return [{"name": n, "status": status} for n in nomes]


@contextlib.contextmanager
def _banco(tabelas=None, erros=None):
    b = _Banco(tabelas, erros)
    with patch("app.db.supabase.get_supabase", return_value=b):
        yield b


def _nomes_de_em_conversa(linha) -> list[str]:
    return [t.template_name for t in cj.CADENCIAS["em_conversa"].linhas[linha].touches]


def _todos_os_templates_de(codigo) -> list[str]:
    return [t.template_name
            for linha in cj.LINHAS
            for t in cj.CADENCIAS[codigo].linhas[linha].touches
            if t.template_name]


def _joao(payload) -> dict:
    return payload["joao"]


def _cadencia(payload, codigo) -> dict:
    return next(c for c in _joao(payload)["cadencias"] if c["codigo"] == codigo)


def _linha(cadencia_payload, linha) -> dict:
    return next(l for l in cadencia_payload["linhas"] if l["linha"] == linha)


def _problemas(resposta) -> list[dict]:
    return resposta.json()["detail"]["problemas"]


def _texto(resposta) -> str:
    return " ".join(p["mensagem"] for p in _problemas(resposta))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. REGRESSÃO: a definição da ValerIA não muda
# ═══════════════════════════════════════════════════════════════════════════════
class TestRegressaoValeria:
    """`followup-board.tsx` lê estas chaves NO TOPO. Mexer aqui apaga a esteira da
    tela sem erro nenhum — o pior modo de falha possível para um painel."""

    def test_as_quatro_chaves_do_consumidor_continuam_no_topo(self):
        payload = build_cadence_definition()
        assert set(payload) >= {"touches", "outbound_nudge", "min_gap_hours",
                                "business_window"}

    def test_os_toques_da_valeria_sao_os_de_cadence_py_na_ordem(self):
        touches = build_cadence_definition()["touches"]
        assert [t["sequence"] for t in touches] == [t.sequence for t in CADENCE]
        assert [t["objective"] for t in touches] == [t.objective for t in CADENCE]

    def test_o_toque_da_valeria_mantem_as_cinco_chaves(self):
        t1 = build_cadence_definition()["touches"][0]
        assert set(t1) == {"sequence", "offset_hours", "jitter_minutes", "objective",
                           "objective_prompt"}
        assert t1["offset_hours"] == 0.0
        assert t1["jitter_minutes"] == [90, 210]

    def test_nudge_gap_e_janela_intactos(self):
        payload = build_cadence_definition()
        assert payload["outbound_nudge"]["offset_hours"] == 18.0
        assert payload["outbound_nudge"]["objective"] == OUTBOUND_NUDGE.objective
        assert payload["min_gap_hours"] == MIN_GAP.total_seconds() / 3600
        assert payload["business_window"] == {
            "start": "09:00", "end": "16:00", "days": "seg-sex",
            "timezone": "America/Sao_Paulo",
        }

    def test_o_bloco_valeria_nomeado_e_identico_ao_topo(self):
        """A chave nova `valeria` existe para o seletor da tela (J5) — e tem de ser a
        MESMA definição, não uma segunda cópia que possa divergir."""
        payload = build_cadence_definition()
        assert payload["valeria"]["touches"] == payload["touches"]
        assert payload["valeria"]["business_window"] == payload["business_window"]

    def test_o_joao_nao_vaza_para_dentro_do_bloco_da_valeria(self):
        payload = build_cadence_definition()
        assert "joao" not in payload["valeria"]
        assert "cadencias" not in payload

    def test_http_devolve_o_mesmo_que_a_funcao_pura(self):
        with _banco():
            r = client.get(GET_URL)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["touches"] == build_cadence_definition()["touches"]
        assert corpo["business_window"] == build_cadence_definition()["business_window"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET: a definição do João
# ═══════════════════════════════════════════════════════════════════════════════
class TestGetJoao:

    def test_traz_as_quatro_cadencias_na_ordem_do_codigo(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert [c["codigo"] for c in _joao(payload)["cadencias"]] == list(cj.CODIGOS)

    def test_cada_cadencia_traz_as_duas_linhas(self):
        with _banco():
            payload = client.get(GET_URL).json()
        for c in _joao(payload)["cadencias"]:
            assert [l["linha"] for l in c["linhas"]] == list(cj.LINHAS)

    @pytest.mark.parametrize("codigo", cj.CODIGOS)
    def test_sem_override_os_dias_e_templates_sao_os_do_codigo(self, codigo):
        with _banco():
            payload = client.get(GET_URL).json()
        c = _cadencia(payload, codigo)
        assert c["gatilho_dias"] == cj.CADENCIAS[codigo].gatilho_dias
        assert c["gatilho_stage_key"] == cj.CADENCIAS[codigo].gatilho_stage_key
        for linha in cj.LINHAS:
            do_codigo = cj.CADENCIAS[codigo].linhas[linha].touches
            toques = _linha(c, linha)["toques"]
            assert [t["sequence"] for t in toques] == [t.sequence for t in do_codigo]
            assert [t["dias"] for t in toques] == [t.offset.days for t in do_codigo]
            assert [t["template_name"] for t in toques] == [
                t.template_name for t in do_codigo]

    def test_tudo_nasce_desligado(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert [c["ativa"] for c in _joao(payload)["cadencias"]] == [False] * 4

    def test_o_override_do_banco_vence_o_codigo(self):
        tabelas = {
            "followup_joao_cadencia": [_cad("reposicao", gatilho_dias=60, ativa=True)],
            "followup_joao_toque": [
                _toque("reposicao", ATACADO, 2, dias=20,
                       template_name="joao_reposicao_atacado_t2_v2"),
            ],
        }
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        c = _cadencia(payload, "reposicao")
        assert c["gatilho_dias"] == 60
        assert c["ativa"] is True
        t2 = _linha(c, ATACADO)["toques"][1]
        assert t2["dias"] == 20
        assert t2["template_name"] == "joao_reposicao_atacado_t2_v2"
        # A outra linha não foi tocada: a sobreposição é por (cadência, linha, toque).
        assert _linha(c, PRIVATE)["toques"][1]["dias"] == 15

    def test_override_parcial_nao_apaga_o_resto(self):
        """Gravar só os dias não pode apagar o template — é a regra que o
        `resolver_cadencia` implementa campo a campo, e que a API tem de preservar."""
        tabelas = {"followup_joao_toque": [_toque("novo", ATACADO, 1, dias=4)]}
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        t1 = _linha(_cadencia(payload, "novo"), ATACADO)["toques"][0]
        assert t1["dias"] == 4
        assert t1["template_name"] == "joao_novo_atacado_t1"

    def test_o_payload_diz_o_que_o_codigo_manda_por_baixo_da_sobreposicao(self):
        """A tela precisa mostrar "padrão 45" ao lado do 60 gravado, senão ninguém
        descobre o que a configuração mudou nem como voltar."""
        tabelas = {
            "followup_joao_cadencia": [_cad("reposicao", gatilho_dias=60)],
            "followup_joao_toque": [_toque("reposicao", ATACADO, 1, dias=7)],
        }
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        c = _cadencia(payload, "reposicao")
        assert c["gatilho_dias_codigo"] == 45
        assert _linha(c, ATACADO)["toques"][0]["dias_codigo"] == 0

    def test_diz_quais_toques_estao_sem_template(self):
        with _banco():
            payload = client.get(GET_URL).json()
        em_atencao = _cadencia(payload, "em_atencao")
        for linha in cj.LINHAS:
            assert _linha(em_atencao, linha)["toques_sem_template"] == [1]
        novo = _cadencia(payload, "novo")
        assert _linha(novo, ATACADO)["toques_sem_template"] == []

    def test_diz_que_em_atencao_ainda_nao_pode_ser_ligada(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert _cadencia(payload, "em_atencao")["pode_ligar"] is False
        assert _cadencia(payload, "em_conversa")["pode_ligar"] is True

    def test_repete_ultimo_viaja_no_payload(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert _cadencia(payload, "em_atencao")["repete_ultimo"] is True
        assert _cadencia(payload, "reposicao")["repete_ultimo"] is False

    def test_migration_nao_aplicada_nao_derruba_o_get(self):
        """A migration roda À MÃO: em produção o endpoint vai encontrar as tabelas
        INEXISTENTES (PGRST205) até alguém aplicá-la. Cair no código é o certo;
        devolver 500 deixaria a aba Follow-up inteira — inclusive a da ValerIA —
        vazia por causa de uma tabela que ainda não existe."""
        erro = Exception("PGRST205: Could not find the table 'followup_joao_toque'")
        with _banco(erros={"followup_joao_cadencia": erro, "followup_joao_toque": erro}):
            r = client.get(GET_URL)
        assert r.status_code == 200, r.text
        c = _cadencia(r.json(), "reposicao")
        assert c["gatilho_dias"] == 45
        assert c["ativa"] is False
        assert r.json()["touches"] == build_cadence_definition()["touches"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PUT: grava a sobreposição (merge, nunca replace)
# ═══════════════════════════════════════════════════════════════════════════════
class TestPutGravacao:

    def test_grava_os_dias_de_um_toque_nas_duas_linhas(self):
        """Sem `linha` no corpo o `dias` vale para a cadência inteira — os offsets são
        simétricos entre Atacado e Private Label no código, e a tela edita "o toque 2",
        não "o toque 2 do Atacado"."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_conversa",
                                          "toques": {"2": {"dias": 3}}})
        assert r.status_code == 200, r.text
        linhas = b.escritas_em("followup_joao_toque")
        assert sorted((x["linha"], x["toque"], x["dias"]) for x in linhas) == [
            (ATACADO, 2, 3), (PRIVATE, 2, 3)]

    def test_template_exige_a_linha_explicita(self):
        """O template é específico da linha (o texto do Atacado não serve para Private
        Label). Gravar o mesmo nome nas duas mandaria o texto errado para metade da
        base — e ninguém descobriria pela tela."""
        with _banco() as b:
            r = client.put(PUT_URL, json={
                "cadencia": "em_conversa",
                "toques": {"2": {"template_name": "joao_conversa_atacado_t2"}},
            })
        assert r.status_code == 400, r.text
        assert "linha" in _texto(r).lower()
        assert b.escritas == []

    def test_com_linha_grava_so_naquela_linha(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={
                "cadencia": "em_conversa", "linha": ATACADO,
                "toques": {"2": {"template_name": "outro_t2", "dias": 3}},
            })
        assert r.status_code == 200, r.text
        linhas = b.escritas_em("followup_joao_toque")
        assert [(x["linha"], x["toque"]) for x in linhas] == [(ATACADO, 2)]
        assert linhas[0]["template_name"] == "outro_t2"

    def test_merge_nao_apaga_o_que_ja_estava_gravado(self):
        """O corpo com só `dias` não pode derrubar o `template_name` já configurado —
        é a diferença entre merge e replace, e um upsert ingênuo faz replace."""
        tabelas = {"followup_joao_toque": [
            _toque("novo", ATACADO, 1, dias=9, template_name="ja_configurado",
                   atualizado_por="joao"),
        ]}
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"cadencia": "novo", "linha": ATACADO,
                                          "toques": {"1": {"dias": 5}}})
        assert r.status_code == 200, r.text
        gravada = b.escritas_em("followup_joao_toque")[0]
        assert gravada["dias"] == 5
        assert gravada["template_name"] == "ja_configurado"
        assert gravada["atualizado_por"] == "joao"

    def test_null_explicito_devolve_o_campo_para_o_codigo(self):
        """Ausente e `null` não são a mesma coisa: ausente é "não mexe", `null` é
        "apaga a sobreposição e volta a valer o código" — é o botão de desfazer."""
        tabelas = {"followup_joao_toque": [
            _toque("novo", ATACADO, 1, dias=9, template_name="ja_configurado")]}
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"cadencia": "novo", "linha": ATACADO,
                                          "toques": {"1": {"dias": None}}})
        assert r.status_code == 200, r.text
        gravada = b.escritas_em("followup_joao_toque")[0]
        assert gravada["dias"] is None
        assert gravada["template_name"] == "ja_configurado"
        t1 = _linha(r.json(), ATACADO)["toques"][0]
        assert t1["dias"] == 0          # o valor do código voltou a valer

    def test_grava_o_prazo_do_gatilho(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "reposicao", "gatilho_dias": 60})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"cadencia": "reposicao", "gatilho_dias": 60}]
        assert r.json()["gatilho_dias"] == 60

    def test_o_upsert_usa_a_chave_primaria_das_tabelas(self):
        """`on_conflict` errado transforma edição em linha duplicada — e a segunda
        linha nunca é lida, então a tela mostra o valor novo e o motor usa o velho."""
        with _banco() as b:
            client.put(PUT_URL, json={"cadencia": "novo", "gatilho_dias": 3,
                                      "toques": {"1": {"dias": 1}}})
        por_tabela = {e["tabela"]: e["on_conflict"] for e in b.escritas}
        assert por_tabela["followup_joao_cadencia"] == "cadencia"
        assert por_tabela["followup_joao_toque"] == "cadencia,linha,toque"

    def test_corpo_sem_nada_a_gravar_nao_toca_o_banco(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo"})
        assert r.status_code == 200, r.text
        assert b.escritas == []

    def test_updated_at_nunca_e_reescrito_a_mao(self):
        """O `updated_at` é do trigger. Reenviar o valor lido faria a coluna congelar
        na data da primeira gravação."""
        tabelas = {"followup_joao_toque": [_toque("novo", ATACADO, 1, dias=9)]}
        with _banco(tabelas) as b:
            client.put(PUT_URL, json={"cadencia": "novo", "linha": ATACADO,
                                      "toques": {"1": {"dias": 5}}})
        assert "updated_at" not in b.escritas_em("followup_joao_toque")[0]

    def test_a_resposta_e_a_cadencia_ja_resolvida(self):
        with _banco():
            r = client.put(PUT_URL, json={"cadencia": "em_conversa",
                                          "toques": {"3": {"dias": 6}}})
        corpo = r.json()
        assert corpo["codigo"] == "em_conversa"
        assert [l["linha"] for l in corpo["linhas"]] == list(cj.LINHAS)
        assert _linha(corpo, ATACADO)["toques"][2]["dias"] == 6

    def test_grava_quem_editou_quando_o_corpo_diz(self):
        with _banco() as b:
            client.put(PUT_URL, json={"cadencia": "novo", "gatilho_dias": 3,
                                      "atualizado_por": "joao@canastra"})
        assert b.escritas_em("followup_joao_cadencia")[0]["atualizado_por"] == \
            "joao@canastra"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PUT: a forma da cadência NÃO é editável (spec §5)
# ═══════════════════════════════════════════════════════════════════════════════
class TestPutTravasDeForma:

    @pytest.mark.parametrize("codigo,fora", [("novo", 2), ("em_conversa", 8),
                                             ("reposicao", 5), ("em_atencao", 2)])
    def test_sequence_fora_do_intervalo_e_recusada(self, codigo, fora):
        """A TRAVA. Sem ela a tela volta a ser um builder: o toque extra é gravado,
        aparece configurado e o motor o ignora em silêncio (`resolver_cadencia`
        descarta sequence que não existe). Mesma regra do CHECK
        `followup_joao_toque_dentro_da_cadencia`."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": codigo,
                                          "toques": {str(fora): {"dias": 3}}})
        assert r.status_code == 400, r.text
        assert str(fora) in _texto(r)
        assert b.escritas == [], "gravou um toque que o código não declara"

    def test_a_recusa_diz_quais_toques_existem(self):
        with _banco():
            r = client.put(PUT_URL, json={"cadencia": "em_conversa",
                                          "toques": {"9": {"dias": 3}}})
        assert "1" in _texto(r) and "7" in _texto(r)
        assert _problemas(r)[0]["codigo"] == "toque_inexistente"

    def test_sequence_zero_ou_negativa_e_recusada(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo",
                                          "toques": {"0": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_sequence_que_nao_e_numero_e_recusada(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo",
                                          "toques": {"t1": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_cadencia_desconhecida_e_404(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "inventada",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert b.escritas == []

    def test_linha_desconhecida_e_404(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo", "linha": "varejo",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert b.escritas == []

    def test_dias_negativo_e_recusado(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo",
                                          "toques": {"1": {"dias": -1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_ordem_invertida_entre_toques_e_recusada(self):
        """Toque 3 antes do toque 2 não quebra nada visível no banco — aparece lá na
        frente, como o lead recebendo a despedida antes da oferta."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_conversa",
                                          "toques": {"3": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_gatilho_zero_e_recusado(self):
        """Espelha o CHECK `followup_joao_cadencia_gatilho_positivo`: zero dia pegaria
        o card no instante em que ele entra na etapa, e a cadência inteira perde o
        sentido de "parado há N dias"."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "reposicao", "gatilho_dias": 0})
        assert r.status_code == 400, r.text
        assert b.escritas == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PUT: a trava de ativação
# ═══════════════════════════════════════════════════════════════════════════════
class TestTravaDeAtivacao:

    def test_ligar_em_atencao_e_sempre_recusado_hoje(self):
        """Os 24 templates aprovados em 13/09/2026 cobrem Novo, Em conversa e
        Reposição. "Em atenção" nasceu depois do lote e não tem texto aprovado — então
        ligá-la é recusado até alguém configurar o template pela tela."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == [], "ligou (ou gravou) uma cadência sem template"
        assert {p["codigo"] for p in _problemas(r)} == {"toque_sem_template"}

    def test_a_recusa_nomeia_a_linha_e_a_sequencia_de_cada_toque_sem_template(self):
        with _banco():
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": True})
        problemas = _problemas(r)
        assert {(p["linha"], p["sequence"]) for p in problemas} == {
            (ATACADO, 1), (PRIVATE, 1)}
        texto = _texto(r)
        assert "Atacado" in texto and "Private Label" in texto
        assert "toque 1" in texto

    def test_a_recusa_olha_as_DUAS_linhas(self):
        """Metade configurada é o caso perigoso: a tela mostraria o Atacado inteiro
        verde e o Private Label não receberia nada."""
        tabelas = {"followup_joao_toque": [
            _toque("em_atencao", ATACADO, 1, template_name="joao_atencao_atacado_t1")]}
        templates = {"message_templates": _templates("joao_atencao_atacado_t1")}
        with _banco({**tabelas, **templates}):
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 400, r.text
        assert [(p["linha"], p["sequence"]) for p in _problemas(r)] == [(PRIVATE, 1)]

    def test_ligar_com_tudo_aprovado_nas_duas_linhas_passa(self):
        nomes = _todos_os_templates_de("em_conversa")
        with _banco({"message_templates": _templates(*nomes)}) as b:
            r = client.put(PUT_URL, json={"cadencia": "em_conversa", "ativa": True})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"cadencia": "em_conversa", "ativa": True}]
        assert r.json()["ativa"] is True

    def test_template_pendente_bloqueia_e_a_recusa_diz_o_status(self):
        """PENDING existe e está certo — a ação é ESPERAR, e é isso que a mensagem tem
        de dizer. "Não está aprovado" devolve a pessoa para a Meta sem saber o que
        procurar."""
        nomes = _todos_os_templates_de("novo")
        linhas = _templates(nomes[0]) + _templates(nomes[1], status="PENDING")
        with _banco({"message_templates": linhas}) as b:
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == []
        assert _problemas(r)[0]["codigo"] == "template_nao_aprovado"
        texto = _texto(r)
        assert nomes[1] in texto and "PENDING" in texto
        assert "aprovação" in texto.lower()

    def test_template_rejeitado_manda_corrigir_e_ressubmeter(self):
        nomes = _todos_os_templates_de("novo")
        linhas = _templates(nomes[0]) + _templates(nomes[1], status="REJECTED")
        with _banco({"message_templates": linhas}):
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 400, r.text
        assert "REJECTED" in _texto(r)
        assert "submeta" in _texto(r).lower()

    def test_template_ausente_da_meta_diz_que_ele_nao_existe(self):
        """Ausente pede CRIAR, não esperar: é o estado em que um nome digitado errado
        na tela cai, e dizer "não aprovado" mandaria a pessoa procurar o que não há."""
        nomes = _todos_os_templates_de("novo")
        with _banco({"message_templates": _templates(nomes[0])}):
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 400, r.text
        assert nomes[1] in _texto(r)
        assert "NÃO EXISTE" in _texto(r)

    def test_espelho_por_canal_com_um_aprovado_basta(self):
        """`message_templates` tem uma linha-espelho POR CANAL e o sync tem buracos —
        ficar com a última linha reprovaria template que a Meta aprovou. Mesmo critério
        de `campaigns/router.api_activate_campaign`."""
        nomes = _todos_os_templates_de("novo")
        linhas = (_templates(nomes[0]) + _templates(nomes[1])
                  + _templates(nomes[1], status="PENDING"))
        with _banco({"message_templates": linhas}):
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 200, r.text

    def test_mapa_vazio_reprova(self):
        """`{}` é uma RESPOSTA ("a Meta não conhece nenhum desses nomes") e reprova —
        estado inicial de qualquer template que nunca foi submetido."""
        with _banco({"message_templates": []}):
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 400, r.text
        assert "NÃO EXISTE" in _texto(r)

    def test_falha_na_consulta_faz_fail_open_so_na_regra_de_template(self):
        """`None` é "não deu para consultar" — travar a ativação por um timeout do
        Supabase é pior do que o risco que a guarda cobre (a tela já escolhe entre
        aprovados). O par com o teste acima é o que pega o atalho
        `if not templates: templates = None`."""
        erro = Exception("timeout")
        with _banco({"followup_joao_toque": []}, erros={"message_templates": erro}) as b:
            r = client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"cadencia": "novo", "ativa": True}]

    def test_fail_open_nao_anistia_o_toque_sem_template(self):
        """Oscilação de banco não é anistia para a metade da regra que não depende da
        Meta: toque SEM NOME continua reprovando."""
        erro = Exception("timeout")
        with _banco(erros={"message_templates": erro}) as b:
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_desligar_nunca_exige_template(self):
        """Desligar tem de funcionar sempre — inclusive (e principalmente) numa
        cadência quebrada."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": False})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"cadencia": "em_atencao", "ativa": False}]

    def test_gravar_dias_sem_ligar_nao_exige_template(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_atencao",
                                          "toques": {"1": {"dias": 5}}})
        assert r.status_code == 200, r.text
        assert len(b.escritas_em("followup_joao_toque")) == 2

    def test_o_template_do_proprio_corpo_conta_na_trava(self):
        """Configurar o template e ligar no MESMO PUT tem de funcionar: a trava olha a
        configuração RESULTANTE, não a que estava no banco antes."""
        nome = "joao_atencao_atacado_t1"
        outro = "joao_atencao_privatelabel_t1"
        tabelas = {
            "followup_joao_toque": [_toque("em_atencao", PRIVATE, 1,
                                           template_name=outro)],
            "message_templates": _templates(nome, outro),
        }
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={
                "cadencia": "em_atencao", "linha": ATACADO, "ativa": True,
                "toques": {"1": {"template_name": nome}},
            })
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_toque")[0]["template_name"] == nome
        assert r.json()["ativa"] is True

    def test_ativacao_recusada_nao_grava_NADA(self):
        """Nem o gatilho, nem os dias, nem o `ativa`. Uma recusa que grava metade
        deixa a configuração num estado que ninguém pediu — e a tela mostra erro em
        cima de dado já alterado."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "em_atencao", "ativa": True,
                                          "gatilho_dias": 120,
                                          "toques": {"1": {"dias": 5}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_a_consulta_a_meta_leva_so_os_templates_da_cadencia(self):
        nomes = _todos_os_templates_de("novo")
        with _banco({"message_templates": _templates(*nomes)}) as b:
            client.put(PUT_URL, json={"cadencia": "novo", "ativa": True})
        assert b.nomes_consultados == [sorted(nomes)]

    def test_nao_consulta_a_meta_quando_nao_esta_ligando(self):
        with _banco({"message_templates": []}) as b:
            client.put(PUT_URL, json={"cadencia": "novo", "gatilho_dias": 3})
        assert "message_templates" not in b.tabelas_tocadas

# backend/tests/test_api_definicao_joao_2026_09_18.py
"""A API da definição das cadências — GET /api/cadence/definition e PUT /api/cadence/joao.

Adaptada em 2026-09-21 (spec `2026-09-21-followup-funil-por-funil-design.md`) para o
João virar funil-primeiro: o payload troca `cadencias: [...]` por `funis: [...]`, e o
PUT passa a exigir `funil` (não mais `linha?` opcional com fallback "aplica nas
duas"). Os casos originais não foram descartados — foram RENOMEADOS e reescopados
para (funil, cadência) no lugar de (cadência, linha).

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

4. **Ligar exige template aprovado em TODO toque do par (funil, cadência).** É a
   guarda mais cara do projeto, e a razão: template que não envia não impede a
   MATRÍCULA, só o envio — a cadência inscreve o card, não manda nada e caminha até o
   fim, registrando "não teve resposta" para quem nunca foi contatado.

   Desde 23/09/2026 essa trava vale para QUATRO das cinco cadências, não mais só para
   "Em atenção": o dono do funil desconectou os 16 templates de Novo, Em conversa e
   Proposta Enviada (spec `2026-09-23-esteiras-joao-v2-design.md` §2) para que os
   textos passem a ser preenchidos pela tela, sem deploy. Enquanto ninguém preencher,
   ligar qualquer uma das três é RECUSADO — e isso é uma declaração do
   `cadence_joao.py`, não um bug a consertar reconectando os nomes antigos. Só
   `reposicao` ainda nasce com template no código, e é por isso que os casos de
   "tudo aprovado" desta suíte migraram para ela (ver `CADENCIA_COM_TEMPLATE`).

5. **Atacado e Private Label deixaram de estar acoplados** (spec §2, decisão 1):
   ligar/desligar/configurar um funil não pode vazar para o funil-irmão que
   compartilha o mesmo código de cadência.

6. **Três campos SÓ-LEITURA no payload da cadência** (spec 2026-09-23 §5/§6):
   `gatilho_silencio_dias` (o segundo relógio do gatilho), `etapa_final_rotulo` e
   `dias_ate_mover` (para onde o card vai no fim, e quando). Vêm do código, não têm
   coluna em tabela nenhuma, e o PUT os ignora EM SILÊNCIO — a tela ecoar no PUT o
   objeto que recebeu do GET não pode virar 400.

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

ATACADO = "atacado"
PRIVATE_LABEL = "private_label"
REPOSICAO_ATACADO = "reposicao_atacado"
REPOSICAO_PRIVATE_LABEL = "reposicao_private_label"
RECUPERACAO = "recuperacao"

# As três de PROSPECÇÃO (spec 2026-09-23): moram em Atacado e Private Label, e desde
# 23/09/2026 NENHUMA tem template em nenhum toque.
PROSPECCAO = ("novo", "em_conversa", "proposta")

# A ÚNICA cadência que ainda nasce com template no código — os 4 `joao_reposicao_*`
# do funil, aprovados na Meta em 13/09/2026. É ela que os casos de "tudo aprovado"
# usam: com as três de prospecção desconectadas, não sobrou outra que passe na trava
# sem um override de template inventado pelo próprio teste.
CADENCIA_COM_TEMPLATE = (REPOSICAO_ATACADO, "reposicao")


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


def _toque(funil, cadencia, toque, *, dias=None, template_name=None,
          atualizado_por=None):
    """Uma linha de `followup_joao_toque` como o PostgREST devolve (PK nova:
    funil, cadencia, toque)."""
    return {"funil": funil, "cadencia": cadencia, "toque": toque, "dias": dias,
            "template_name": template_name, "atualizado_por": atualizado_por,
            "updated_at": "2026-09-18T12:00:00+00:00"}


def _cad(funil, cadencia, *, gatilho_dias=None, ativa=None, atualizado_por=None):
    """Uma linha de `followup_joao_cadencia` (PK nova: funil, cadencia)."""
    return {"funil": funil, "cadencia": cadencia, "gatilho_dias": gatilho_dias,
            "ativa": ativa, "atualizado_por": atualizado_por,
            "updated_at": "2026-09-18T12:00:00+00:00"}


def _templates(*nomes, status="APPROVED"):
    return [{"name": n, "status": status} for n in nomes]


@contextlib.contextmanager
def _banco(tabelas=None, erros=None):
    b = _Banco(tabelas, erros)
    with patch("app.db.supabase.get_supabase", return_value=b):
        yield b


def _todos_os_templates_de(funil_codigo, codigo) -> list[str]:
    cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
    return [t.template_name for t in cadencia.touches if t.template_name]


def _joao(payload) -> dict:
    return payload["joao"]


def _funil(payload, codigo) -> dict:
    return next(f for f in _joao(payload)["funis"] if f["codigo"] == codigo)


def _cadencia(funil_payload, codigo) -> dict:
    return next(c for c in funil_payload["cadencias"] if c["codigo"] == codigo)


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
        assert "funis" not in payload

    def test_http_devolve_o_mesmo_que_a_funcao_pura(self):
        with _banco():
            r = client.get(GET_URL)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["touches"] == build_cadence_definition()["touches"]
        assert corpo["business_window"] == build_cadence_definition()["business_window"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GET: a definição do João — funil é o eixo
# ═══════════════════════════════════════════════════════════════════════════════
class TestGetJoao:

    def test_traz_os_cinco_funis_na_ordem_do_codigo(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert [f["codigo"] for f in _joao(payload)["funis"]] == list(cj.FUNIL_CODIGOS)
        assert len(cj.FUNIL_CODIGOS) == 5

    def test_cada_funil_traz_rotulo_completo_e_pipeline_id(self):
        with _banco():
            payload = client.get(GET_URL).json()
        for f in _joao(payload)["funis"]:
            esperado = cj.funil(f["codigo"])
            assert f["rotulo"] == esperado.rotulo
            assert f["pipeline_id"] == esperado.pipeline_id
        # Nomes completos, não os rótulos genéricos "Atacado"/"Private Label" de antes.
        assert _funil(payload, ATACADO)["rotulo"] == "João - Atacado"
        assert _funil(payload, REPOSICAO_ATACADO)["rotulo"] == "João - Reposição Atacado"

    def test_recuperacao_aparece_como_funil_de_verdade_com_cadencias_vazias(self):
        with _banco():
            payload = client.get(GET_URL).json()
        recuperacao = _funil(payload, RECUPERACAO)
        assert recuperacao["rotulo"] == "João - Recuperação"
        assert recuperacao["pipeline_id"] == cj.PIPELINE_RECUPERACAO
        assert recuperacao["cadencias"] == []

    @pytest.mark.parametrize("funil_codigo,codigo", [
        (ATACADO, "novo"), (ATACADO, "em_conversa"), (ATACADO, "proposta"),
        (PRIVATE_LABEL, "novo"), (PRIVATE_LABEL, "em_conversa"),
        (PRIVATE_LABEL, "proposta"),
        (REPOSICAO_ATACADO, "reposicao"), (REPOSICAO_ATACADO, "em_atencao"),
        (REPOSICAO_PRIVATE_LABEL, "reposicao"), (REPOSICAO_PRIVATE_LABEL, "em_atencao"),
    ])
    def test_sem_override_os_dias_e_templates_sao_os_do_codigo(self, funil_codigo, codigo):
        with _banco():
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, funil_codigo), codigo)
        cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
        assert c["gatilho_dias"] == cadencia.gatilho_dias
        assert c["gatilho_stage_key"] == cadencia.gatilho_stage_key
        assert c["gatilho_stage_rotulo"] == cadencia.gatilho_stage_rotulo
        toques = c["toques"]
        assert [t["sequence"] for t in toques] == [t.sequence for t in cadencia.touches]
        assert [t["dias"] for t in toques] == [t.offset.days for t in cadencia.touches]
        assert [t["template_name"] for t in toques] == [
            t.template_name for t in cadencia.touches]

    def test_tudo_nasce_desligado(self):
        with _banco():
            payload = client.get(GET_URL).json()
        for f in _joao(payload)["funis"]:
            for c in f["cadencias"]:
                assert c["ativa"] is False

    def test_o_override_do_banco_vence_o_codigo_e_nao_vaza_pro_funil_irmao(self):
        tabelas = {
            "followup_joao_cadencia": [_cad(REPOSICAO_ATACADO, "reposicao",
                                            gatilho_dias=60, ativa=True)],
            "followup_joao_toque": [
                _toque(REPOSICAO_ATACADO, "reposicao", 2, dias=20,
                       template_name="joao_reposicao_atacado_t2_v2"),
            ],
        }
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, REPOSICAO_ATACADO), "reposicao")
        assert c["gatilho_dias"] == 60
        assert c["ativa"] is True
        t2 = c["toques"][1]
        assert t2["dias"] == 20
        assert t2["template_name"] == "joao_reposicao_atacado_t2_v2"
        # O funil-irmão não foi tocado: a sobreposição é por (funil, cadência, toque).
        irmao = _cadencia(_funil(payload, REPOSICAO_PRIVATE_LABEL), "reposicao")
        assert irmao["gatilho_dias"] == 45
        assert irmao["ativa"] is False
        assert irmao["toques"][1]["dias"] == 15

    def test_override_parcial_nao_apaga_o_resto(self):
        """Gravar só os dias não pode apagar o template — é a regra que o
        `resolver_cadencia` implementa campo a campo, e que a API tem de preservar.

        Em `reposicao` porque é a única cadência que ainda TEM template no código
        para ser apagado (23/09/2026): nas três de prospecção o campo já nasce nulo,
        e o teste passaria por acidente."""
        tabelas = {"followup_joao_toque": [
            _toque(REPOSICAO_ATACADO, "reposicao", 1, dias=4)]}
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        t1 = _cadencia(_funil(payload, REPOSICAO_ATACADO), "reposicao")["toques"][0]
        assert t1["dias"] == 4
        assert t1["template_name"] == "joao_reposicao_atacado_t1"

    def test_o_payload_diz_o_que_o_codigo_manda_por_baixo_da_sobreposicao(self):
        """A tela precisa mostrar "padrão 45" ao lado do 60 gravado, senão ninguém
        descobre o que a configuração mudou nem como voltar."""
        tabelas = {
            "followup_joao_cadencia": [_cad(REPOSICAO_ATACADO, "reposicao",
                                            gatilho_dias=60)],
            "followup_joao_toque": [_toque(REPOSICAO_ATACADO, "reposicao", 1, dias=7)],
        }
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, REPOSICAO_ATACADO), "reposicao")
        assert c["gatilho_dias_codigo"] == 45
        assert c["toques"][0]["dias_codigo"] == 0

    def test_diz_quais_toques_estao_sem_template(self):
        """TODOS os toques das três de prospecção (spec 2026-09-23 §2) e o único de
        "Em atenção". Só `reposicao` sai limpa."""
        with _banco():
            payload = client.get(GET_URL).json()
        em_atencao_atacado = _cadencia(_funil(payload, REPOSICAO_ATACADO), "em_atencao")
        assert em_atencao_atacado["toques_sem_template"] == [1]
        em_atencao_private = _cadencia(_funil(payload, REPOSICAO_PRIVATE_LABEL),
                                       "em_atencao")
        assert em_atencao_private["toques_sem_template"] == [1]
        assert _cadencia(_funil(payload, REPOSICAO_ATACADO),
                         "reposicao")["toques_sem_template"] == []
        for funil_codigo in (ATACADO, PRIVATE_LABEL):
            f = _funil(payload, funil_codigo)
            assert _cadencia(f, "novo")["toques_sem_template"] == [1, 2, 3]
            assert _cadencia(f, "em_conversa")["toques_sem_template"] == [1, 2, 3, 4]
            assert _cadencia(f, "proposta")["toques_sem_template"] == [1, 2, 3, 4]

    def test_so_reposicao_pode_ser_ligada_hoje(self):
        """Quatro das cinco cadências não podem ser ligadas: "Em atenção" nunca teve
        template, e as três de prospecção foram DESCONECTADAS dos 16 delas em
        23/09/2026 (spec §2). É o que o dono pediu, e a tela tem de dizer isso antes
        de alguém tentar o PUT."""
        with _banco():
            payload = client.get(GET_URL).json()
        assert _cadencia(_funil(payload, REPOSICAO_ATACADO),
                         "em_atencao")["pode_ligar"] is False
        assert _cadencia(_funil(payload, REPOSICAO_ATACADO),
                         "reposicao")["pode_ligar"] is True
        for funil_codigo in (ATACADO, PRIVATE_LABEL):
            f = _funil(payload, funil_codigo)
            for codigo in PROSPECCAO:
                assert _cadencia(f, codigo)["pode_ligar"] is False, codigo

    def test_repete_ultimo_viaja_no_payload(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert _cadencia(_funil(payload, REPOSICAO_ATACADO),
                         "em_atencao")["repete_ultimo"] is True
        assert _cadencia(_funil(payload, REPOSICAO_ATACADO),
                         "reposicao")["repete_ultimo"] is False

    def test_gatilho_stage_rotulo_de_em_atencao_e_cliente_ativo_nunca_em_atencao(self):
        """Armadilha da spec §2: as cadências "reposicao" e "em_atencao" vigiam a
        MESMA etapa ("Cliente Ativo", key `novo`) — usar o nome da cadência como
        rótulo da etapa reintroduziria a confusão que funil-primeiro corrige."""
        with _banco():
            payload = client.get(GET_URL).json()
        em_atencao = _cadencia(_funil(payload, REPOSICAO_ATACADO), "em_atencao")
        assert em_atencao["gatilho_stage_key"] == "novo"
        assert em_atencao["gatilho_stage_rotulo"] == "Cliente Ativo"
        reposicao = _cadencia(_funil(payload, REPOSICAO_ATACADO), "reposicao")
        assert reposicao["gatilho_stage_rotulo"] == "Cliente Ativo"

    def test_migration_nao_aplicada_nao_derruba_o_get(self):
        """A migration roda À MÃO: em produção o endpoint vai encontrar as tabelas
        INEXISTENTES (PGRST205) até alguém aplicá-la. Cair no código é o certo;
        devolver 500 deixaria a aba Follow-up inteira — inclusive a da ValerIA —
        vazia por causa de uma tabela que ainda não existe."""
        erro = Exception("PGRST205: Could not find the table 'followup_joao_toque'")
        with _banco(erros={"followup_joao_cadencia": erro, "followup_joao_toque": erro}):
            r = client.get(GET_URL)
        assert r.status_code == 200, r.text
        payload = r.json()
        c = _cadencia(_funil(payload, REPOSICAO_ATACADO), "reposicao")
        assert c["gatilho_dias"] == 45
        assert c["ativa"] is False
        assert payload["touches"] == build_cadence_definition()["touches"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2b. GET: a TERCEIRA cadência e os três campos só-leitura (spec 2026-09-23)
# ═══════════════════════════════════════════════════════════════════════════════
class TestTerceiraCadenciaEOsCamposNovos:
    """"Proposta Enviada" não precisou de uma linha na API: o endpoint já itera
    `funil.cadencias` inteiro. Esta classe existe para PROVAR isso — se alguém
    voltar a achatar o payload por código de cadência, é aqui que quebra."""

    def test_atacado_e_private_label_devolvem_as_TRES_cadencias(self):
        with _banco():
            payload = client.get(GET_URL).json()
        for funil_codigo in (ATACADO, PRIVATE_LABEL):
            codigos = [c["codigo"] for c in _funil(payload, funil_codigo)["cadencias"]]
            assert codigos == list(PROSPECCAO), funil_codigo

    def test_os_funis_de_reposicao_continuam_com_DUAS(self):
        """O spec de 23/09 reformula só a prospecção (§7, "o que NÃO muda"). Uma
        terceira cadência aparecendo aqui seria vazamento da mudança."""
        with _banco():
            payload = client.get(GET_URL).json()
        for funil_codigo in (REPOSICAO_ATACADO, REPOSICAO_PRIVATE_LABEL):
            codigos = [c["codigo"] for c in _funil(payload, funil_codigo)["cadencias"]]
            assert codigos == ["reposicao", "em_atencao"], funil_codigo

    def test_recuperacao_continua_com_ZERO(self):
        with _banco():
            payload = client.get(GET_URL).json()
        assert _funil(payload, RECUPERACAO)["cadencias"] == []

    def test_proposta_traz_gatilho_etapa_e_toques_proprios(self):
        """A cadência nova por inteiro: vigia "Proposta Enviada" (a etapa em que o
        /orcamento já larga o card sozinho), dispara em 1 dia, 4 toques em 0/1/4/8."""
        with _banco():
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, ATACADO), "proposta")
        assert c["rotulo"] == "Proposta Enviada"
        assert c["job_type"] == "joao_proposta"
        assert c["gatilho_stage_key"] == "proposta_enviada"
        assert c["gatilho_stage_rotulo"] == "Proposta Enviada"
        assert c["gatilho_dias"] == 1
        assert [t["dias"] for t in c["toques"]] == [0, 1, 4, 8]
        assert [t["template_name"] for t in c["toques"]] == [None] * 4

    @pytest.mark.parametrize("funil_codigo,codigo,silencio,destino,dias_ate_mover", [
        # As três de prospecção: silêncio 2 em Novo e Em conversa (o dono escreveu
        # "2 dias sem conversar"), 0 em Proposta ("24h depois" é tempo de ETAPA — a
        # proposta recém-enviada é justamente o momento em que houve conversa).
        (ATACADO, "novo", 2, "Em atenção", 1),
        (ATACADO, "em_conversa", 2, "Em atenção", 1),
        (ATACADO, "proposta", 0, "Em atenção", 1),
        (PRIVATE_LABEL, "novo", 2, "Em atenção", 1),
        (PRIVATE_LABEL, "em_conversa", 2, "Em atenção", 1),
        (PRIVATE_LABEL, "proposta", 0, "Em atenção", 1),
        # As duas de Reposição: o relógio delas é mesmo o da etapa, e elas NÃO movem
        # card nenhum — `etapa_final_rotulo` nulo é o que diz isso à tela.
        (REPOSICAO_ATACADO, "reposicao", 0, None, 1),
        (REPOSICAO_ATACADO, "em_atencao", 0, None, 1),
        (REPOSICAO_PRIVATE_LABEL, "reposicao", 0, None, 1),
        (REPOSICAO_PRIVATE_LABEL, "em_atencao", 0, None, 1),
    ])
    def test_os_tres_campos_so_leitura_no_payload(self, funil_codigo, codigo, silencio,
                                                  destino, dias_ate_mover):
        with _banco():
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, funil_codigo), codigo)
        assert c["gatilho_silencio_dias"] == silencio
        assert c["etapa_final_rotulo"] == destino
        assert c["dias_ate_mover"] == dias_ate_mover

    def test_os_tres_campos_vem_do_codigo_e_o_banco_NAO_os_sobrepoe(self):
        """Eles não têm coluna nas tabelas de sobreposição (spec §5: "o de silêncio
        fica só no código"). Uma linha gravada com esses nomes — de um PUT ingênuo, ou
        de alguém editando o banco à mão — não pode vazar para o payload."""
        tabelas = {"followup_joao_cadencia": [
            {**_cad(ATACADO, "novo", gatilho_dias=9),
             "gatilho_silencio_dias": 99, "etapa_final_rotulo": "Perdido",
             "dias_ate_mover": 77},
        ]}
        with _banco(tabelas):
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, ATACADO), "novo")
        assert c["gatilho_dias"] == 9          # esse SIM é sobreposto
        assert c["gatilho_silencio_dias"] == 2
        assert c["etapa_final_rotulo"] == "Em atenção"
        assert c["dias_ate_mover"] == 1

    def test_o_rotulo_do_destino_e_hardcoded_nunca_o_codigo_da_etapa(self):
        """`etapa_final_rotulo` é texto para humano ("Em atenção"), não a key
        (`em_atencao`) — e `pipeline_stages.label` é editável por qualquer operador do
        CRM, então ele nunca pode vir do banco. Mesma regra de
        `gatilho_stage_rotulo` (spec 2026-09-21, decisão 2)."""
        with _banco():
            payload = client.get(GET_URL).json()
        c = _cadencia(_funil(payload, ATACADO), "novo")
        assert c["etapa_final_rotulo"] == "Em atenção"
        assert "etapa_final_key" not in c, (
            "a key da etapa é contrato do agendador/handler, não da tela")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PUT: grava a sobreposição de UM (funil, cadência) — merge, nunca replace
# ═══════════════════════════════════════════════════════════════════════════════
class TestPutGravacao:

    def test_grava_os_dias_de_um_toque_so_no_funil_pedido(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "em_conversa",
                                          "toques": {"2": {"dias": 3}}})
        assert r.status_code == 200, r.text
        linhas = b.escritas_em("followup_joao_toque")
        assert [(x["funil"], x["cadencia"], x["toque"], x["dias"]) for x in linhas] == [
            (ATACADO, "em_conversa", 2, 3)]

    def test_template_nao_exige_mais_campo_separado_de_linha(self):
        """O `funil` do corpo já identifica a linha de produto de forma única — não
        existe mais "informe `linha` porque o template é específico dela"."""
        with _banco() as b:
            r = client.put(PUT_URL, json={
                "funil": ATACADO, "cadencia": "em_conversa",
                "toques": {"2": {"template_name": "joao_conversa_atacado_t2"}},
            })
        assert r.status_code == 200, r.text
        linhas = b.escritas_em("followup_joao_toque")
        assert linhas[0]["template_name"] == "joao_conversa_atacado_t2"

    def test_grava_so_no_funil_pedido_nao_no_irmao(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={
                "funil": ATACADO, "cadencia": "em_conversa",
                "toques": {"2": {"template_name": "outro_t2", "dias": 3}},
            })
        assert r.status_code == 200, r.text
        linhas = b.escritas_em("followup_joao_toque")
        assert [(x["funil"], x["toque"]) for x in linhas] == [(ATACADO, 2)]
        assert linhas[0]["template_name"] == "outro_t2"

    def test_merge_nao_apaga_o_que_ja_estava_gravado(self):
        """O corpo com só `dias` não pode derrubar o `template_name` já configurado —
        é a diferença entre merge e replace, e um upsert ingênuo faz replace."""
        tabelas = {"followup_joao_toque": [
            _toque(ATACADO, "novo", 1, dias=9, template_name="ja_configurado",
                   atualizado_por="joao"),
        ]}
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 200, r.text
        gravada = b.escritas_em("followup_joao_toque")[0]
        assert gravada["dias"] == 1
        assert gravada["template_name"] == "ja_configurado"
        assert gravada["atualizado_por"] == "joao"

    def test_null_explicito_devolve_o_campo_para_o_codigo(self):
        """Ausente e `null` não são a mesma coisa: ausente é "não mexe", `null` é
        "apaga a sobreposição e volta a valer o código" — é o botão de desfazer."""
        tabelas = {"followup_joao_toque": [
            _toque(ATACADO, "novo", 1, dias=9, template_name="ja_configurado")]}
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "toques": {"1": {"dias": None}}})
        assert r.status_code == 200, r.text
        gravada = b.escritas_em("followup_joao_toque")[0]
        assert gravada["dias"] is None
        assert gravada["template_name"] == "ja_configurado"
        t1 = r.json()["toques"][0]
        assert t1["dias"] == 0          # o valor do código voltou a valer

    def test_grava_o_prazo_do_gatilho(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "reposicao", "gatilho_dias": 60})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": REPOSICAO_ATACADO, "cadencia": "reposicao", "gatilho_dias": 60}]
        assert r.json()["gatilho_dias"] == 60

    def test_o_upsert_usa_a_chave_primaria_das_tabelas(self):
        """`on_conflict` errado transforma edição em linha duplicada — e a segunda
        linha nunca é lida, então a tela mostra o valor novo e o motor usa o velho."""
        with _banco() as b:
            client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                      "gatilho_dias": 3, "toques": {"1": {"dias": 1}}})
        por_tabela = {e["tabela"]: e["on_conflict"] for e in b.escritas}
        assert por_tabela["followup_joao_cadencia"] == "funil,cadencia"
        assert por_tabela["followup_joao_toque"] == "funil,cadencia,toque"

    def test_corpo_sem_nada_a_gravar_nao_toca_o_banco(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo"})
        assert r.status_code == 200, r.text
        assert b.escritas == []

    def test_updated_at_nunca_e_reescrito_a_mao(self):
        """O `updated_at` é do trigger. Reenviar o valor lido faria a coluna congelar
        na data da primeira gravação."""
        tabelas = {"followup_joao_toque": [_toque(ATACADO, "novo", 1, dias=9)]}
        with _banco(tabelas) as b:
            client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                      "toques": {"1": {"dias": 1}}})
        assert "updated_at" not in b.escritas_em("followup_joao_toque")[0]

    def test_a_resposta_e_a_cadencia_ja_resolvida(self):
        with _banco():
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "em_conversa",
                                          "toques": {"3": {"dias": 6}}})
        corpo = r.json()
        assert corpo["codigo"] == "em_conversa"
        assert corpo["toques"][2]["dias"] == 6

    def test_grava_quem_editou_quando_o_corpo_diz(self):
        with _banco() as b:
            client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                      "gatilho_dias": 3,
                                      "atualizado_por": "joao@canastra"})
        assert b.escritas_em("followup_joao_cadencia")[0]["atualizado_por"] == \
            "joao@canastra"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PUT: a forma da cadência NÃO é editável, e `funil` é obrigatório (spec §5)
# ═══════════════════════════════════════════════════════════════════════════════
class TestPutTravasDeForma:

    @pytest.mark.parametrize("funil_codigo,codigo,fora", [
        # Os limites mudaram em 23/09/2026: `novo` foi de 1 para 3 toques,
        # `em_conversa` de 7 para 4, e `proposta` nasceu com 4.
        (ATACADO, "novo", 4), (ATACADO, "em_conversa", 5), (ATACADO, "proposta", 5),
        (PRIVATE_LABEL, "proposta", 0),
        (REPOSICAO_ATACADO, "reposicao", 5), (REPOSICAO_ATACADO, "em_atencao", 2),
    ])
    def test_sequence_fora_do_intervalo_e_recusada(self, funil_codigo, codigo, fora):
        """A TRAVA. Sem ela a tela volta a ser um builder: o toque extra é gravado,
        aparece configurado e o motor o ignora em silêncio (`resolver_cadencia`
        descarta sequence que não existe). Mesma regra do CHECK
        `followup_joao_toque_dentro_da_cadencia`."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "toques": {str(fora): {"dias": 3}}})
        assert r.status_code == 400, r.text
        assert str(fora) in _texto(r)
        assert b.escritas == [], "gravou um toque que o código não declara"

    def test_a_recusa_diz_quais_toques_existem(self):
        """"Em conversa" tem 1 a 4 desde 23/09/2026 (eram 7 toques ao longo de ~30
        dias). A recusa tem de citar o intervalo REAL — se citasse o antigo, mandaria
        a pessoa tentar de novo um toque que não existe mais."""
        with _banco():
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "em_conversa",
                                          "toques": {"9": {"dias": 3}}})
        assert "os toques 1 a 4" in _texto(r)
        assert _problemas(r)[0]["codigo"] == "toque_inexistente"

    def test_sequence_zero_ou_negativa_e_recusada(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "toques": {"0": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_sequence_que_nao_e_numero_e_recusada(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "toques": {"t1": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_funil_ausente_e_404(self):
        """Não existe mais "aplica nas duas" — `funil` é obrigatório."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"cadencia": "novo",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert b.escritas == []

    def test_funil_desconhecido_e_404(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": "inventado", "cadencia": "novo",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert "inventado" in r.json()["detail"]
        assert b.escritas == []

    def test_cadencia_desconhecida_e_404(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "inventada",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert b.escritas == []

    def test_par_funil_cadencia_invalido_nomeia_as_cadencias_daquele_funil(self):
        """`funil=atacado, cadencia=reposicao` não é um par válido — a recusa nomeia
        as cadências de "João - Atacado" (novo, em_conversa), não a lista genérica
        dos 4 códigos, que confundiria mais do que ajudaria (spec §5)."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "reposicao",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        detalhe = r.json()["detail"]
        assert "novo" in detalhe and "em_conversa" in detalhe
        assert "em_atencao" not in detalhe  # não é cadência de "João - Atacado"
        assert b.escritas == []

    def test_par_invalido_no_funil_recuperacao_diz_que_nao_tem_cadencia(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": RECUPERACAO, "cadencia": "novo",
                                          "toques": {"1": {"dias": 1}}})
        assert r.status_code == 404, r.text
        assert "nenhuma cadência" in r.json()["detail"]
        assert b.escritas == []

    def test_dias_negativo_e_recusado(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "toques": {"1": {"dias": -1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_ordem_invertida_entre_toques_e_recusada(self):
        """Toque 3 antes do toque 2 não quebra nada visível no banco — aparece lá na
        frente, como o lead recebendo a despedida antes da oferta."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "em_conversa",
                                          "toques": {"3": {"dias": 1}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_gatilho_zero_e_recusado(self):
        """Espelha o CHECK `followup_joao_cadencia_gatilho_positivo`: zero dia pegaria
        o card no instante em que ele entra na etapa, e a cadência inteira perde o
        sentido de "parado há N dias"."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "reposicao", "gatilho_dias": 0})
        assert r.status_code == 400, r.text
        assert b.escritas == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PUT: a trava de ativação — agora escopada a UM (funil, cadência) por vez
# ═══════════════════════════════════════════════════════════════════════════════
class TestTravaDeAtivacao:

    def test_ligar_em_atencao_e_sempre_recusado_hoje(self):
        """Os 24 templates aprovados em 13/09/2026 cobrem Novo, Em conversa e
        Reposição. "Em atenção" nasceu depois do lote e não tem texto aprovado — então
        ligá-la é recusado até alguém configurar o template pela tela."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == [], "ligou (ou gravou) uma cadência sem template"
        assert {p["codigo"] for p in _problemas(r)} == {"toque_sem_template"}

    def test_a_recusa_nomeia_o_funil_e_a_sequencia_de_cada_toque_sem_template(self):
        with _banco():
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": True})
        problemas = _problemas(r)
        assert [(p["funil"], p["cadencia"], p["sequence"]) for p in problemas] == [
            (REPOSICAO_ATACADO, "em_atencao", 1)]
        assert "toque 1" in _texto(r)

    def test_a_recusa_nao_vaza_para_o_funil_irmao(self):
        """Ativar 'Em atenção' do Reposição Atacado não olha o Reposição Private
        Label — os dois funis deixaram de estar acoplados (spec §2, decisão 1)."""
        nome = "joao_atencao_atacado_t1"
        tabelas = {
            "followup_joao_toque": [_toque(REPOSICAO_ATACADO, "em_atencao", 1,
                                           template_name=nome)],
            "message_templates": _templates(nome),
        }
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": REPOSICAO_ATACADO, "cadencia": "em_atencao", "ativa": True}]

    def test_ligar_com_tudo_aprovado_passa(self):
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        with _banco({"message_templates": _templates(*nomes)}) as b:
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": funil_codigo, "cadencia": codigo, "ativa": True}]
        assert r.json()["ativa"] is True

    def test_ligar_um_funil_nao_consulta_templates_do_irmao(self):
        """Ligar 'Reposição' do Reposição Atacado não pede os templates do Reposição
        Private Label — cada funil é uma linha própria de liga/desliga agora."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        with _banco({"message_templates": _templates(*nomes)}) as b:
            client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                      "ativa": True})
        nomes_privados = _todos_os_templates_de(REPOSICAO_PRIVATE_LABEL, codigo)
        assert nomes_privados, "o funil-irmão perdeu os templates — teste vazio passa"
        assert not (set(nomes_privados) & set(b.nomes_consultados[0]))

    def test_template_pendente_bloqueia_e_a_recusa_diz_o_status(self):
        """PENDING existe e está certo — a ação é ESPERAR, e é isso que a mensagem tem
        de dizer. "Não está aprovado" devolve a pessoa para a Meta sem saber o que
        procurar."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        linhas = _templates(*nomes[:-1]) + _templates(nomes[-1], status="PENDING")
        with _banco({"message_templates": linhas}) as b:
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == []
        assert _problemas(r)[0]["codigo"] == "template_nao_aprovado"
        texto = _texto(r)
        assert nomes[-1] in texto and "PENDING" in texto
        assert "aprovação" in texto.lower()

    def test_template_rejeitado_manda_corrigir_e_ressubmeter(self):
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        linhas = _templates(*nomes[:-1]) + _templates(nomes[-1], status="REJECTED")
        with _banco({"message_templates": linhas}):
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert "REJECTED" in _texto(r)
        assert "submeta" in _texto(r).lower()

    def test_template_ausente_da_meta_diz_que_ele_nao_existe(self):
        """Ausente pede CRIAR, não esperar: é o estado em que um nome digitado errado
        na tela cai, e dizer "não aprovado" mandaria a pessoa procurar o que não há."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        with _banco({"message_templates": _templates(*nomes[:-1])}):
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert nomes[-1] in _texto(r)
        assert "NÃO EXISTE" in _texto(r)

    def test_espelho_por_canal_com_um_aprovado_basta(self):
        """`message_templates` tem uma linha-espelho POR CANAL e o sync tem buracos —
        ficar com a última linha reprovaria template que a Meta aprovou. Mesmo critério
        de `campaigns/router.api_activate_campaign`."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        linhas = (_templates(*nomes[:-1]) + _templates(nomes[-1])
                  + _templates(nomes[-1], status="PENDING"))
        with _banco({"message_templates": linhas}):
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 200, r.text

    def test_mapa_vazio_reprova(self):
        """`{}` é uma RESPOSTA ("a Meta não conhece nenhum desses nomes") e reprova —
        estado inicial de qualquer template que nunca foi submetido."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        with _banco({"message_templates": []}):
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert "NÃO EXISTE" in _texto(r)

    def test_falha_na_consulta_faz_fail_open_so_na_regra_de_template(self):
        """`None` é "não deu para consultar" — travar a ativação por um timeout do
        Supabase é pior do que o risco que a guarda cobre (a tela já escolhe entre
        aprovados). O par com o teste acima é o que pega o atalho
        `if not templates: templates = None`."""
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        erro = Exception("timeout")
        with _banco({"followup_joao_toque": []}, erros={"message_templates": erro}) as b:
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": funil_codigo, "cadencia": codigo, "ativa": True}]

    def test_fail_open_nao_anistia_o_toque_sem_template(self):
        """Oscilação de banco não é anistia para a metade da regra que não depende da
        Meta: toque SEM NOME continua reprovando."""
        erro = Exception("timeout")
        with _banco(erros={"message_templates": erro}) as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_desligar_nunca_exige_template(self):
        """Desligar tem de funcionar sempre — inclusive (e principalmente) numa
        cadência quebrada."""
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": False})
        assert r.status_code == 200, r.text
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": REPOSICAO_ATACADO, "cadencia": "em_atencao", "ativa": False}]

    def test_gravar_dias_sem_ligar_nao_exige_template(self):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao",
                                          "toques": {"1": {"dias": 5}}})
        assert r.status_code == 200, r.text
        assert len(b.escritas_em("followup_joao_toque")) == 1

    def test_o_template_do_proprio_corpo_conta_na_trava(self):
        """Configurar o template e ligar no MESMO PUT tem de funcionar: a trava olha a
        configuração RESULTANTE, não a que estava no banco antes."""
        nome = "joao_atencao_atacado_t1"
        with _banco({"message_templates": _templates(nome)}) as b:
            r = client.put(PUT_URL, json={
                "funil": REPOSICAO_ATACADO, "cadencia": "em_atencao", "ativa": True,
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
            r = client.put(PUT_URL, json={"funil": REPOSICAO_ATACADO,
                                          "cadencia": "em_atencao", "ativa": True,
                                          "gatilho_dias": 120,
                                          "toques": {"1": {"dias": 5}}})
        assert r.status_code == 400, r.text
        assert b.escritas == []

    def test_a_consulta_a_meta_leva_so_os_templates_da_cadencia(self):
        funil_codigo, codigo = CADENCIA_COM_TEMPLATE
        nomes = _todos_os_templates_de(funil_codigo, codigo)
        with _banco({"message_templates": _templates(*nomes)}) as b:
            client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                      "ativa": True})
        assert b.nomes_consultados == [sorted(nomes)]

    def test_nao_consulta_a_meta_quando_nao_esta_ligando(self):
        with _banco({"message_templates": []}) as b:
            client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                      "gatilho_dias": 3})
        assert "message_templates" not in b.tabelas_tocadas


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PUT depois de 23/09/2026: as três de prospecção não ligam, e os campos
#    só-leitura não quebram nada
# ═══════════════════════════════════════════════════════════════════════════════
class TestProspeccaoNaoLigaHoje:
    """O teste que o dono do funil pediu por escrito, e o motivo dele:

    os 22 toques das três cadências nasceram SEM template (spec 2026-09-23 §2). Se a
    trava não valesse, ligar uma delas inscreveria o card, não mandaria mensagem
    nenhuma e caminharia até o fim — inclusive movendo o card para "Em atenção" —
    registrando "não teve resposta" para um lead que nunca foi contatado. É
    exatamente o estrago que `_ENVIO_MUDO` descreve, e agora ele cabe em 6 das 6
    cadências de prospecção (3 códigos × 2 funis) em vez de só em "Em atenção"."""

    @pytest.mark.parametrize("funil_codigo", [ATACADO, PRIVATE_LABEL])
    @pytest.mark.parametrize("codigo", PROSPECCAO)
    def test_ligar_qualquer_uma_das_tres_e_recusado(self, funil_codigo, codigo):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": funil_codigo, "cadencia": codigo,
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == [], "ligou uma cadência sem template em nenhum toque"
        assert {p["codigo"] for p in _problemas(r)} == {"toque_sem_template"}

    @pytest.mark.parametrize("codigo,quantos", [
        ("novo", 3), ("em_conversa", 4), ("proposta", 4),
    ])
    def test_a_recusa_nomeia_TODOS_os_toques_vazios_um_a_um(self, codigo, quantos):
        """Um problema por toque, com a sequence dentro — a tela destaca o toque
        culpado, e uma recusa genérica ("faltam templates") obrigaria a pessoa a
        descobrir quais abrindo um por um."""
        with _banco():
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": codigo,
                                          "ativa": True})
        problemas = _problemas(r)
        assert [(p["funil"], p["cadencia"], p["sequence"]) for p in problemas] == [
            (ATACADO, codigo, s) for s in range(1, quantos + 1)]
        texto = _texto(r)
        for s in range(1, quantos + 1):
            assert f"toque {s} não tem template configurado" in texto

    def test_a_recusa_explica_a_CONSEQUENCIA_nao_so_a_falta(self):
        """O estrago não é "não enviou", é "registrou que não teve resposta"."""
        with _banco():
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "ativa": True})
        assert "não teve resposta" in _texto(r)

    def test_nem_com_o_template_de_METADE_dos_toques(self):
        """Preencher só uma parte não libera: a trava é por TODO toque. É o caso mais
        provável na prática — alguém preenche o primeiro texto e tenta ligar."""
        nome = "joao_novo_atacado_t1"
        tabelas = {
            "followup_joao_toque": [_toque(ATACADO, "novo", 1, template_name=nome)],
            "message_templates": _templates(nome),
        }
        with _banco(tabelas) as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "ativa": True})
        assert r.status_code == 400, r.text
        assert b.escritas == []
        assert [p["sequence"] for p in _problemas(r)] == [2, 3]

    def test_preencher_os_tres_pela_TELA_libera_o_liga(self):
        """O caminho de saída, e ele existe sem deploy: configurar os templates e
        ligar no MESMO PUT. É o que faz a recusa acima ser uma trava e não um beco."""
        nomes = [f"joao_novo_atacado_t{n}" for n in (1, 2, 3)]
        with _banco({"message_templates": _templates(*nomes)}) as b:
            r = client.put(PUT_URL, json={
                "funil": ATACADO, "cadencia": "novo", "ativa": True,
                "toques": {str(i): {"template_name": n}
                           for i, n in enumerate(nomes, start=1)},
            })
        assert r.status_code == 200, r.text
        assert r.json()["ativa"] is True
        assert r.json()["pode_ligar"] is True
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": ATACADO, "cadencia": "novo", "ativa": True}]

    def test_desligar_as_tres_continua_sempre_possivel(self):
        """Desligar nunca exige template — inclusive (e principalmente) numa cadência
        que não pode ser ligada."""
        for codigo in PROSPECCAO:
            with _banco() as b:
                r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": codigo,
                                              "ativa": False})
            assert r.status_code == 200, r.text
            assert b.escritas_em("followup_joao_cadencia") == [
                {"funil": ATACADO, "cadencia": codigo, "ativa": False}]


class TestPutIgnoraOsCamposSoLeitura:
    """A tela ecoa no PUT o objeto de cadência que recebeu do GET — é o caminho mais
    provável de integração, e um campo só-leitura que explode quando ecoado é uma
    armadilha, não uma guarda. Os três são IGNORADOS EM SILÊNCIO, nunca 400."""

    @pytest.mark.parametrize("campo,valor", [
        ("gatilho_silencio_dias", 9),
        ("etapa_final_rotulo", "Perdido"),
        ("dias_ate_mover", 30),
    ])
    def test_um_campo_so_leitura_no_corpo_nao_recusa_nem_grava(self, campo, valor):
        with _banco() as b:
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "proposta",
                                          campo: valor})
        assert r.status_code == 200, r.text
        assert b.escritas == [], f"gravou `{campo}`, que não é coluna de sobreposição"
        assert r.json()[campo] != valor

    def test_a_cadencia_do_GET_volta_inteira_no_PUT(self):
        """O caso real: a tela devolve a cadência como veio, com um `gatilho_dias`
        mexido. TODAS as chaves só-leitura viajam junto — os três novos, mas também
        `rotulo`, `job_type`, `pode_ligar`, `toques_sem_template`, os `*_codigo` — e
        nenhuma pode estragar a gravação.

        `toques` sai do corpo, e a razão é ANTERIOR a esta entrega: no GET ele é uma
        LISTA e no PUT é um MAPA {sequence: {...}}. Ecoar a lista dá 400
        `toques_invalidos` — recusa correta pela regra que já existe, e não é o que
        este teste mede. Quem consome tem de montar o mapa; está no docstring da rota
        (`toques?: {sequence: {dias?, template_name?}}`)."""
        with _banco():
            payload = client.get(GET_URL).json()
        corpo = dict(_cadencia(_funil(payload, ATACADO), "proposta"))
        corpo.pop("toques")
        assert "gatilho_silencio_dias" in corpo and "dias_ate_mover" in corpo
        corpo.update({"funil": ATACADO, "cadencia": "proposta", "gatilho_dias": 3})
        with _banco() as b:
            r = client.put(PUT_URL, json=corpo)
        assert r.status_code == 200, r.text
        # `ativa` veio no eco e FOI gravado — e tem de ser assim: `ativa` é campo
        # EDITÁVEL, não só-leitura, e o valor ecoado (False) é o que o GET acabou de
        # dizer. O que este teste separa é editável de só-leitura, não "ignore tudo".
        assert b.escritas_em("followup_joao_cadencia") == [
            {"funil": ATACADO, "cadencia": "proposta", "gatilho_dias": 3,
             "ativa": False}]
        resolvida = r.json()
        assert resolvida["gatilho_dias"] == 3
        assert resolvida["gatilho_silencio_dias"] == 0
        assert resolvida["etapa_final_rotulo"] == "Em atenção"
        assert resolvida["dias_ate_mover"] == 1

    def test_a_resposta_do_PUT_traz_os_tres_campos(self):
        """O GET e o PUT devolvem a MESMA forma de cadência — a tela consome os dois
        com um tipo só, e um campo faltando no PUT quebraria o cabeçalho depois de
        salvar."""
        with _banco():
            r = client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "novo",
                                          "gatilho_dias": 4})
        corpo = r.json()
        assert corpo["gatilho_silencio_dias"] == 2
        assert corpo["etapa_final_rotulo"] == "Em atenção"
        assert corpo["dias_ate_mover"] == 1

    def test_gravar_dias_e_template_de_proposta_funciona_normalmente(self):
        """A cadência nova não é um caso especial do PUT: o par (funil, cadência) é
        `(atacado, proposta)` e o resto da rota não mudou."""
        with _banco() as b:
            r = client.put(PUT_URL, json={
                "funil": ATACADO, "cadencia": "proposta",
                "toques": {"2": {"dias": 2, "template_name": "joao_proposta_t2"}},
            })
        assert r.status_code == 200, r.text
        gravada = b.escritas_em("followup_joao_toque")[0]
        assert (gravada["funil"], gravada["cadencia"], gravada["toque"]) == (
            ATACADO, "proposta", 2)
        assert gravada["dias"] == 2
        assert gravada["template_name"] == "joao_proposta_t2"
        t2 = r.json()["toques"][1]
        assert t2["dias"] == 2
        assert t2["dias_codigo"] == 1          # o que o código manda por baixo
        assert t2["template_name_codigo"] is None

    def test_proposta_do_atacado_nao_vaza_para_o_private_label(self):
        with _banco() as b:
            client.put(PUT_URL, json={"funil": ATACADO, "cadencia": "proposta",
                                      "toques": {"1": {"template_name": "so_atacado"}}})
        assert [(x["funil"], x["cadencia"]) for x in
                b.escritas_em("followup_joao_toque")] == [(ATACADO, "proposta")]

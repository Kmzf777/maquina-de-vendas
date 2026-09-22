# backend/tests/test_cadence_joao_2026_09_18.py
"""Contrato das cadências de follow-up do vendedor João, por FUNIL.

`app/follow_up/cadence_joao.py` é config-as-code, no mesmo molde de
`follow_up/cadence.py` (a cadência da ValerIA): dataclass congelada + tupla de
toques, função pura, zero I/O. A diferença que justifica um módulo novo é uma só:
o lead do João está em SILÊNCIO por definição — a janela de 24h da Meta está
fechada — então o toque não é texto de LLM, é **template aprovado**. Por isso o
`Touch` daqui carrega `template_name` onde o da ValerIA carrega `objective_prompt`.

Reescrito em 21/09/2026 (spec
`docs/superpowers/specs/2026-09-21-followup-funil-por-funil-design.md`) para
funil-primeiro: o eixo deixou de ser a cadência (com duas "linhas" genéricas dentro)
e passou a ser o FUNIL (`Funil{codigo, rotulo, pipeline_id, cadencias}`) — cada
cadência mora dentro de UM funil, identificado pelo par `(funil, codigo)`. Os
NÚMEROS (dias, toques, templates) são os mesmos do arquivo de 18/09/2026; só a
estrutura de dados que os guarda mudou.

O que este arquivo trava:

  1. os números são os da ata de 10/09/2026, não os da memória de quem editar
     (spec 18/09 §4: docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md);
  2. os nomes de template são os 24 REAIS, cruzados contra
     `scripts/create_templates_esteiras_joao.py` — o script que os submeteu à Meta
     e que sobreviveu ao rollback do caminho do builder. Nome de template inventado
     é envio que morre em runtime, no meio da cadência, sem ninguém olhando;
  3. o banco SOBREPÕE o código, e vazio vale o código (requisito da ata 33:28,
     "45 dias, mas opção do João editar o número de dias"), sem nunca conseguir
     ADICIONAR ou REMOVER toque — isso continua sendo mudança de código;
  4. as duas regras de resposta da ata: "ainda tenho estoque" adia 60 dias SEM
     recomeçar a contagem (41:40) e o botão de saída é opt-out real;
  5. NOVO (21/09): cada par (funil, cadência) é único — a mesma string de cadência
     ("novo", "reposicao", ...) nunca aponta para dois pipelines diferentes; e o
     rótulo do gatilho de "Em atenção" é sempre "Cliente Ativo", nunca "Em atenção"
     (a armadilha nomeada na spec §2).

A suíte não tem banco: sobre a migration o único guarda-rail possível é o TEXTO do
arquivo — mesmo padrão de `test_sql_apaga_esteiras_joao_2026_09_18.py`.
"""
import ast
import importlib.util
import re
from dataclasses import FrozenInstanceError
from datetime import timedelta
from pathlib import Path

import pytest

from app.follow_up import cadence_joao as cj

RAIZ = Path(__file__).resolve().parents[2]
SQL_PATH = RAIZ / "supabase" / "migrations" / "20260918_followup_joao_config.sql"
SCRIPT_TEMPLATES = RAIZ / "scripts" / "create_templates_esteiras_joao.py"
MIGRATION_FUNIS = RAIZ / "supabase" / "migrations" / "20260910_contrato_etapas_joao.sql"
MODULO = RAIZ / "backend" / "app" / "follow_up" / "cadence_joao.py"
CADENCE_VALERIA = RAIZ / "backend" / "app" / "follow_up" / "cadence.py"


def _campos_de_dataclass(caminho: Path, nome_classe: str) -> set:
    """Os campos de uma dataclass, lidos do TEXTO via AST — sem importar o módulo.

    `app.follow_up.cadence` (a cadência da ValerIA) importa `app.follow_up.service`,
    que ainda referencia os símbolos antigos deste módulo (`CADENCIAS`, `CODIGOS`,
    `LINHAS`) enquanto o Lote 2 (scheduler/service/api) não fizer o rename
    linha→funil — território de outra task, não deste arquivo. Ler os campos por
    AST mantém o teste fiel ao contrato REAL do arquivo, sem herdar uma quebra de
    import que não é dele.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef) and no.name == nome_classe:
            return {
                alvo.target.id
                for alvo in no.body
                if isinstance(alvo, ast.AnnAssign) and isinstance(alvo.target, ast.Name)
            }
    raise AssertionError(f"classe {nome_classe} não encontrada em {caminho}")

# ── Os números da ata (spec 18/09 §4). Ver o timestamp ao lado de cada um. ──────
#
# offsets em DIAS, contados a partir da MATRÍCULA (o instante em que o gatilho
# disparou), nunca do toque anterior — é assim que `cadence.py` conta e é o que a
# tela vai editar. Indexado por CÓDIGO da cadência: os dois funis-irmãos de cada
# par (Atacado/Private Label, Reposição Atacado/Reposição Private Label) usam os
# mesmos offsets — só o template muda.
OFFSETS = {
    # 01:07:10 "é de dois dias" — um toque só, no disparo do gatilho.
    "novo": [0],
    # 41:02 "deve durar uns 30 dias": D+2/4/7/12/18/24/30 contados da ENTRADA na
    # etapa; o gatilho come os 2 primeiros dias, então da matrícula são estes.
    "em_conversa": [0, 2, 5, 10, 16, 22, 28],
    # 34:24 "o dia 45 ele vai receber uma mensagem... de 15 em 15".
    "reposicao": [0, 15, 30, 45],
    # 38:08/41:12 "uma mensagem a cada três dias até ele falar que não quer mais".
    "em_atencao": [3],
}

GATILHO_DIAS = {
    "novo": 2,          # 01:07:10
    "em_conversa": 2,   # 01:07:10
    "reposicao": 45,    # 26:35, 33:28, 34:24
    "em_atencao": 90,   # 38:08, 41:12
}

GATILHO_STAGE_KEY = {
    "novo": "novo",
    "em_conversa": "respondeu",
    "reposicao": "novo",
    "em_atencao": "novo",
}

# NOVO (21/09): o rótulo hardcoded da etapa que o gatilho vigia. "Cliente Ativo" é a
# key `novo` do funil de Reposição (confirmado em
# `20260910_contrato_etapas_joao.sql:131`) — NUNCA "Em atenção", que é o nome de uma
# etapa DE VERDADE que a cadência "Em atenção" não vigia (spec §2, "Armadilha a
# evitar").
GATILHO_STAGE_ROTULO = {
    "novo": "Novo",
    "em_conversa": "Em conversa",
    "reposicao": "Cliente Ativo",
    "em_atencao": "Cliente Ativo",
}

CODIGOS = ("novo", "em_conversa", "reposicao", "em_atencao")

# Os cinco funis (spec §1). "recuperacao" não tem par válido em CODIGOS — cadência
# vazia, de propósito.
FUNIL_CODIGOS = (
    "atacado", "private_label", "reposicao_atacado", "reposicao_private_label",
    "recuperacao",
)

FUNIS_ATACADO = ("atacado", "reposicao_atacado")
FUNIS_PRIVATE_LABEL = ("private_label", "reposicao_private_label")

# UUIDs de produção dos funis do João, medidos em 10/09/2026. Ficam também em
# supabase/migrations/20260910_contrato_etapas_joao.sql — e o teste
# `test_os_uuids_de_funil_existem_na_migration_dos_funis` cruza os dois.
PIPELINES = {
    "atacado": "9706a14a-3d9a-413b-bceb-26838fc2cc45",
    "private_label": "24fb6ce8-6b7b-4612-970d-8debb8c041b7",
    "reposicao_atacado": "79e35e6b-01d1-482a-bdf0-64c733ff1ca4",
    "reposicao_private_label": "9c027143-72f6-42d6-861f-a494ba5bbb4f",
    "recuperacao": "fa94029b-d524-4550-919e-67233dfe3a94",
}

# Os pares (funil, cadência) que realmente existem — o equivalente novo de
# "(codigo, linha)" na suíte antiga. `recuperacao` não aparece: zero cadência.
PARES = (
    ("atacado", "novo"),
    ("atacado", "em_conversa"),
    ("private_label", "novo"),
    ("private_label", "em_conversa"),
    ("reposicao_atacado", "reposicao"),
    ("reposicao_atacado", "em_atencao"),
    ("reposicao_private_label", "reposicao"),
    ("reposicao_private_label", "em_atencao"),
)


@pytest.fixture(scope="module")
def script_templates():
    """O módulo de `scripts/create_templates_esteiras_joao.py`, importado do disco.

    Importar em vez de redigitar os 24 nomes é o ponto: um teste que repete a
    lista à mão passa a concordar consigo mesmo, não com a Meta.
    """
    assert SCRIPT_TEMPLATES.exists(), SCRIPT_TEMPLATES
    spec = importlib.util.spec_from_file_location("_tpl_joao", SCRIPT_TEMPLATES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def nomes_reais(script_templates) -> set:
    return {t["name"] for t in script_templates.TEMPLATES}


@pytest.fixture(scope="module")
def botoes_por_template(script_templates) -> dict:
    mapa = {}
    for t in script_templates.TEMPLATES:
        mapa[t["name"]] = [
            b["text"]
            for c in t["components"] if c["type"] == "BUTTONS"
            for b in c["buttons"]
        ]
    return mapa


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), f"migration não encontrada em {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_codigo(sql) -> str:
    """O SQL sem comentários — o cabeçalho explica o desenho em português e cita
    os mesmos termos que os testes de comando destrutivo procuram."""
    return "\n".join(linha.split("--", 1)[0] for linha in sql.splitlines())


@pytest.fixture(autouse=True)
def _default_followup_claim_db():
    """Sobrescreve o autouse homônimo de `tests/conftest.py` SÓ NESTE ARQUIVO.

    O autouse de conftest.py faz `monkeypatch.setattr("app.follow_up.scheduler...")`,
    e a resolução de alvo por string do monkeypatch IMPORTA o módulo — que importa
    `app.follow_up.service`, que ainda importa `CADENCIAS`/`CODIGOS`/`LINHAS` do
    `cadence_joao` antigo (rename para funil-primeiro pendente até o Lote 2 —
    `service.py`/`scheduler.py` não são território desta task). Sem este override, TODO
    teste deste arquivo erraria no setup por uma cadeia de import alheia ao que ele
    testa — `cadence_joao.py` é puro, zero I/O, não precisa de Supabase mockado.
    Fixture de mesmo nome definida no módulo do teste tem prioridade sobre a de
    conftest.py (regra padrão do pytest); não é edição de conftest.py, é escopo local.
    """
    yield


@pytest.fixture(autouse=True)
def _stub_catalog():
    """Sobrescreve o autouse `_stub_catalog` de `tests/conftest.py` SÓ NESTE ARQUIVO.

    Mesma classe de problema do override acima, cadeia de import diferente:
    `monkeypatch.setattr("app.agent.orchestrator...")` importa `app.agent.orchestrator`
    → `app.agent.tools` → `app.follow_up.service` → os símbolos antigos de
    `cadence_joao`. Este módulo de teste não usa orchestrator/catálogo — o override
    só existe para não herdar uma quebra de import que é território do Lote 2.
    """
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Os cinco funis, os pares (funil, cadência), os números da ata
# ═══════════════════════════════════════════════════════════════════════════════
class TestOsCincoFunis:
    def test_existem_os_cinco_e_so_eles(self):
        assert cj.FUNIL_CODIGOS == FUNIL_CODIGOS

    def test_funis_tem_exatamente_cinco_entradas(self):
        assert len(cj.FUNIS) == 5

    @pytest.mark.parametrize("funil_codigo", FUNIL_CODIGOS)
    def test_cada_funil_aponta_para_o_pipeline_certo(self, funil_codigo):
        assert cj.funil(funil_codigo).pipeline_id == PIPELINES[funil_codigo]

    def test_os_uuids_de_funil_existem_na_migration_dos_funis(self):
        # Cruzamento com a ÚNICA outra fonte desses UUIDs dentro do repo. Um dígito
        # trocado aqui apontaria a cadência para um funil que não é do João, e o
        # erro só apareceria em produção, como "a esteira não pega ninguém".
        fonte = MIGRATION_FUNIS.read_text(encoding="utf-8")
        for uuid in set(PIPELINES.values()):
            assert uuid in fonte, uuid

    def test_recuperacao_tem_zero_cadencia(self):
        # Espaço reservado — decisão 3 do cabeçalho do módulo. Não é ausência de
        # dado, é o estado real: nenhum gatilho, nenhum toque definido ainda.
        assert cj.funil("recuperacao").cadencias == ()

    @pytest.mark.parametrize("funil_codigo", ("atacado", "private_label",
                                               "reposicao_atacado",
                                               "reposicao_private_label"))
    def test_os_outros_quatro_funis_tem_cadencia(self, funil_codigo):
        assert len(cj.funil(funil_codigo).cadencias) == 2


class TestParesFunilCadencia:
    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_o_par_existe(self, funil_codigo, codigo):
        assert cj.cadencia_do_funil(funil_codigo, codigo) is not None

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_o_prazo_do_gatilho_e_o_da_ata(self, funil_codigo, codigo):
        assert cj.cadencia_do_funil(funil_codigo, codigo).gatilho_dias == \
            GATILHO_DIAS[codigo]

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_a_contagem_de_toques_e_a_da_ata(self, funil_codigo, codigo):
        toques = cj.cadencia_do_funil(funil_codigo, codigo).touches
        assert len(toques) == len(OFFSETS[codigo])

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_os_offsets_sao_os_da_ata(self, funil_codigo, codigo):
        toques = cj.cadencia_do_funil(funil_codigo, codigo).touches
        assert [t.offset for t in toques] == [
            timedelta(days=d) for d in OFFSETS[codigo]
        ]

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_as_sequences_sao_1_ate_n_em_ordem(self, funil_codigo, codigo):
        toques = cj.cadencia_do_funil(funil_codigo, codigo).touches
        assert [t.sequence for t in toques] == list(range(1, len(toques) + 1))

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_gatilho_stage_key_e_o_da_ata(self, funil_codigo, codigo):
        assert cj.cadencia_do_funil(funil_codigo, codigo).gatilho_stage_key == \
            GATILHO_STAGE_KEY[codigo]

    # ── A armadilha nomeada na spec §2: "Em atenção" vigia "Cliente Ativo", NUNCA
    # o rótulo "Em atenção". ──────────────────────────────────────────────────
    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_gatilho_stage_rotulo_e_o_hardcoded_no_codigo(self, funil_codigo, codigo):
        assert cj.cadencia_do_funil(funil_codigo, codigo).gatilho_stage_rotulo == \
            GATILHO_STAGE_ROTULO[codigo]

    @pytest.mark.parametrize("funil_codigo", ("reposicao_atacado",
                                               "reposicao_private_label"))
    def test_em_atencao_nunca_tem_rotulo_em_atencao(self, funil_codigo):
        rotulo = cj.cadencia_do_funil(funil_codigo, "em_atencao").gatilho_stage_rotulo
        assert rotulo == "Cliente Ativo"
        assert rotulo != "Em atenção"

    @pytest.mark.parametrize("funil_codigo", ("reposicao_atacado",
                                               "reposicao_private_label"))
    def test_reposicao_e_em_atencao_vigiam_a_mesma_etapa(self, funil_codigo):
        # "45 dias em Cliente Ativo" e "90 dias sem comprar" são medidos na MESMA
        # etapa (key `novo` do funil de Reposição = a coluna "Cliente Ativo").
        reposicao = cj.cadencia_do_funil(funil_codigo, "reposicao")
        em_atencao = cj.cadencia_do_funil(funil_codigo, "em_atencao")
        assert reposicao.gatilho_stage_key == em_atencao.gatilho_stage_key == "novo"
        assert reposicao.gatilho_stage_rotulo == em_atencao.gatilho_stage_rotulo == \
            "Cliente Ativo"

    def test_novo_vigia_a_etapa_novo_e_em_conversa_a_etapa_respondeu(self):
        # `respondeu` e não `em_conversa`: é a key que 20260910_contrato_etapas_joao
        # atribuiu à coluna "Em conversa" (e que `advance_deal_on_reply` já procura).
        for funil_codigo in ("atacado", "private_label"):
            assert cj.cadencia_do_funil(funil_codigo, "novo").gatilho_stage_key == \
                "novo"
            assert cj.cadencia_do_funil(funil_codigo, "em_conversa").gatilho_stage_key \
                == "respondeu"

    def test_atacado_e_reposicao_atacado_nao_compartilham_pipeline(self):
        # O bug de identidade que a mudança para funil-primeiro corrige (spec §1):
        # "atacado" não é mais uma string ambígua entre dois pipelines diferentes —
        # agora são dois FUNIS diferentes, cada um com seu próprio pipeline_id.
        assert cj.funil("atacado").pipeline_id != cj.funil("reposicao_atacado").pipeline_id


class TestHelpersDeFunil:
    def test_funil_pelo_codigo(self):
        f = cj.funil("atacado")
        assert f is not None
        assert f.codigo == "atacado"
        assert f.rotulo == "João - Atacado"

    def test_funil_desconhecido_devolve_none(self):
        assert cj.funil("varejo") is None

    def test_cadencia_do_funil_par_invalido_devolve_none(self):
        # "atacado" existe, "reposicao" existe, mas o PAR não — Atacado não tem
        # cadência de Reposição.
        assert cj.cadencia_do_funil("atacado", "reposicao") is None

    def test_cadencia_do_funil_funil_inexistente_devolve_none(self):
        assert cj.cadencia_do_funil("varejo", "novo") is None

    def test_cadencia_do_funil_codigo_inexistente_devolve_none(self):
        assert cj.cadencia_do_funil("atacado", "inexistente") is None

    def test_recuperacao_nao_aceita_nenhum_par(self):
        for codigo in CODIGOS:
            assert cj.cadencia_do_funil("recuperacao", codigo) is None


class TestFormaDoDado:
    def test_touch_e_congelado(self):
        toque = cj.cadencia_do_funil("atacado", "novo").touches[0]
        with pytest.raises(FrozenInstanceError):
            toque.offset = timedelta(days=99)

    def test_cadencia_e_congelada(self):
        with pytest.raises(FrozenInstanceError):
            cj.cadencia_do_funil("atacado", "novo").gatilho_dias = 99

    def test_funil_e_congelado(self):
        with pytest.raises(FrozenInstanceError):
            cj.funil("atacado").rotulo = "outro nome"

    def test_os_toques_vivem_numa_tupla(self):
        # Mesma escolha de `cadence.py`: tupla, não lista — ninguém acrescenta toque
        # em runtime por acidente.
        assert isinstance(cj.cadencia_do_funil("atacado", "em_conversa").touches, tuple)

    def test_touch_carrega_template_name_e_nao_objective_prompt(self):
        campos_joao = set(cj.Touch.__dataclass_fields__)
        campos_valeria = _campos_de_dataclass(CADENCE_VALERIA, "Touch")
        assert "template_name" in campos_joao
        assert "objective_prompt" not in campos_joao
        assert "objective_prompt" in campos_valeria  # o contraste é o ponto


class TestTudoNasceDesligado:
    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_nenhuma_cadencia_nasce_ativa(self, funil_codigo, codigo):
        # "Tudo nasce desligado". Medido em 16/09/2026: 888 cards ficam elegíveis
        # no instante em que uma liga.
        assert cj.cadencia_do_funil(funil_codigo, codigo).ativa is False

    def test_sem_override_a_cadencia_resolvida_continua_desligada(self):
        assert cj.resolver("reposicao_atacado", "reposicao", {}).ativa is False


class TestJobType:
    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_o_job_type_e_derivado_do_codigo(self, funil_codigo, codigo):
        assert cj.cadencia_do_funil(funil_codigo, codigo).job_type == f"joao_{codigo}"

    def test_os_job_types_sao_quatro_e_distintos(self):
        assert cj.JOB_TYPES == frozenset(f"joao_{c}" for c in CODIGOS)
        assert len(cj.JOB_TYPES) == 4

    def test_nenhum_job_type_colide_com_os_cinco_que_ja_existem(self):
        # `follow_up_jobs` já é executor multi-tipo. Colidir com um tipo existente
        # faria o job do João cair no handler da ValerIA.
        existentes = {"standard", "ai_scheduled_return", "ai_reengage",
                      "handoff_rescue", "lp_welcome"}
        assert not (cj.JOB_TYPES & existentes)

    def test_funis_irmaos_compartilham_job_type_de_proposito(self):
        # job_type continua ambíguo entre funis que compartilham cadência (ex.
        # reposicao_atacado e reposicao_private_label compartilham
        # job_type="joao_reposicao") — já era assim (Atacado/Private Label
        # compartilhavam joao_novo). Quem resolve o funil certo é o metadata do job.
        a = cj.cadencia_do_funil("reposicao_atacado", "reposicao")
        b = cj.cadencia_do_funil("reposicao_private_label", "reposicao")
        assert a.job_type == b.job_type == "joao_reposicao"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Os templates são os 24 reais
# ═══════════════════════════════════════════════════════════════════════════════
def _templates_declarados():
    return [
        t.template_name
        for f in cj.FUNIS
        for cad in f.cadencias
        for t in cad.touches
        if t.template_name is not None
    ]


class TestOsTemplatesSaoOsReais:
    def test_o_script_ainda_declara_24_templates(self, nomes_reais):
        assert len(nomes_reais) == 24

    def test_todo_template_declarado_existe_no_script(self, nomes_reais):
        declarados = set(_templates_declarados())
        assert declarados <= nomes_reais, declarados - nomes_reais

    def test_os_24_templates_estao_todos_em_uso(self, nomes_reais):
        # O outro lado: template aprovado e esquecido é toque que a ata pediu e a
        # cadência não entrega.
        assert nomes_reais - set(_templates_declarados()) == set()

    def test_nenhum_template_se_repete_entre_toques(self):
        # `broadcast/worker.py::_template_dedup_guardrail` não vale aqui: reusar um
        # nome faria o MESMO texto sair duas vezes para o mesmo lead.
        declarados = _templates_declarados()
        assert len(declarados) == len(set(declarados))

    @pytest.mark.parametrize("funil_codigo,codigo",
                              [p for p in PARES if p[1] != "em_atencao"])
    def test_o_toque_n_usa_o_template_terminado_em_tn(self, funil_codigo, codigo):
        for toque in cj.cadencia_do_funil(funil_codigo, codigo).touches:
            assert toque.template_name.endswith(f"_t{toque.sequence}"), toque

    @pytest.mark.parametrize("codigo", ("novo", "em_conversa", "reposicao"))
    def test_o_funil_do_template_bate_com_o_funil_da_cadencia(self, codigo):
        # Trocar Atacado por Private Label mandaria a cadência inteira com o texto
        # da linha errada, sem erro em lugar nenhum.
        for funil_codigo in FUNIS_ATACADO:
            cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
            if cadencia is None:
                continue
            for toque in cadencia.touches:
                assert "_atacado_" in toque.template_name
        for funil_codigo in FUNIS_PRIVATE_LABEL:
            cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
            if cadencia is None:
                continue
            for toque in cadencia.touches:
                assert "_privatelabel_" in toque.template_name

    def test_em_atencao_ainda_nao_tem_template(self):
        # Os 24 aprovados cobrem Novo, Em conversa e Reposição — a 4ª cadência
        # nasceu depois do lote e NÃO tem texto aprovado na Meta. `None` aqui é
        # declaração, não esquecimento: é o que faz a trava de ativação (API)
        # recusar ligar "Em atenção".
        for funil_codigo in ("reposicao_atacado", "reposicao_private_label"):
            for toque in cj.cadencia_do_funil(funil_codigo, "em_atencao").touches:
                assert toque.template_name is None

    @pytest.mark.parametrize("funil_codigo", ("reposicao_atacado",
                                               "reposicao_private_label"))
    def test_em_atencao_e_a_unica_cadencia_que_nao_pode_ser_ligada(self, funil_codigo):
        assert cj.toques_sem_template(funil_codigo, "em_atencao") == (1,)
        assert cj.toques_sem_template(funil_codigo, "reposicao") == ()

    @pytest.mark.parametrize("funil_codigo", ("atacado", "private_label"))
    def test_novo_e_em_conversa_podem_ser_ligadas(self, funil_codigo):
        assert cj.toques_sem_template(funil_codigo, "novo") == ()
        assert cj.toques_sem_template(funil_codigo, "em_conversa") == ()

    def test_override_de_template_fecha_o_buraco_de_em_atencao(self):
        faltando = cj.toques_sem_template(
            "reposicao_atacado", "em_atencao",
            {"toques": {1: {"template_name": "joao_atencao_atacado_t1"}}},
        )
        assert faltando == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. As duas regras de resposta da ata
# ═══════════════════════════════════════════════════════════════════════════════
class TestAdiamentoDeSessentaDias:
    def test_o_adiamento_e_de_60_dias(self):
        assert cj.ADIAMENTO_ESTOQUE == timedelta(days=60)

    @pytest.mark.parametrize("texto", [
        "Ainda tenho estoque",
        "ainda tenho estoque",
        "AINDA TENHO ESTOQUE",
        "  Ainda  tenho   estoque.  ",
    ])
    def test_o_botao_e_reconhecido_em_qualquer_caixa(self, texto):
        assert cj.classificar_resposta(texto) == cj.RESPOSTA_ADIAR

    @pytest.mark.parametrize("texto", [
        "ainda tenho estoque mas quero ver a tabela",
        "não, não tenho mais estoque",
        "estoque",
        "",
        None,
    ])
    def test_e_igualdade_e_nunca_substring(self, texto):
        # Mesma doutrina de `is_optout_reply`: "ainda tenho estoque mas quero ver a
        # tabela" é um lead QUENTE — adiar 60 dias seria perdê-lo.
        assert cj.classificar_resposta(texto) != cj.RESPOSTA_ADIAR

    def test_o_rotulo_do_adiamento_e_o_que_esta_nos_templates(self, botoes_por_template):
        # A frase é literal da ata (41:40) e literal dos templates aprovados. Se um
        # dia o rótulo do botão mudar na Meta sem mudar aqui, o botão vira MORTO —
        # foi exatamente o que aconteceu com "Nao atendo mais" em produção.
        rotulos = {
            re.sub(r"\s+", " ", b.strip().lower())
            for botoes in botoes_por_template.values() for b in botoes
        }
        assert cj.ROTULOS_ADIAMENTO <= rotulos

    def test_adiar_empurra_os_toques_restantes_em_60_dias(self):
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao")
        adiados = cj.adiar_toques(toques, ultimo_enviado=1)
        assert [t.sequence for t in adiados] == [2, 3, 4]
        assert [t.offset.days for t in adiados] == [15 + 60, 30 + 60, 45 + 60]

    def test_adiar_nao_recomeca_a_contagem(self):
        # 41:40: "adia 60 dias, sem recomeçar". Recomeçar seria devolver a cadência
        # inteira a partir do toque 1 — o lead receberia de novo o texto que já leu.
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao")
        adiados = cj.adiar_toques(toques, ultimo_enviado=2)
        assert [t.sequence for t in adiados] == [3, 4]

    def test_adiar_preserva_o_espacamento_entre_os_toques(self):
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao")
        adiados = cj.adiar_toques(toques, ultimo_enviado=1)
        gaps_antes = [b.offset - a.offset for a, b in zip(toques[1:], toques[2:])]
        gaps_depois = [b.offset - a.offset for a, b in zip(adiados, adiados[1:])]
        assert gaps_antes == gaps_depois

    def test_adiar_depois_do_ultimo_toque_nao_sobra_nada(self):
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao")
        assert cj.adiar_toques(toques, ultimo_enviado=4) == ()

    def test_adiar_nao_muta_a_tupla_de_origem(self):
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao")
        antes = [t.offset for t in toques]
        cj.adiar_toques(toques, ultimo_enviado=1)
        assert [t.offset for t in toques] == antes

    def test_so_aceita_adiamento_o_toque_cujo_template_tem_o_botao(self, botoes_por_template):
        # A verdade está no template aprovado, não na nossa memória: o toque que NÃO
        # tem o botão "Ainda tenho estoque" não pode declarar que aceita o adiamento
        # — ninguém conseguiria apertá-lo.
        for f in cj.FUNIS:
            for cadencia in f.cadencias:
                for toque in cadencia.touches:
                    if toque.template_name is None:
                        continue
                    rotulos = {
                        re.sub(r"\s+", " ", b.strip().lower())
                        for b in botoes_por_template[toque.template_name]
                    }
                    tem_botao = bool(cj.ROTULOS_ADIAMENTO & rotulos)
                    assert toque.aceita_adiamento is tem_botao, toque.template_name

    def test_o_ultimo_toque_da_reposicao_nao_aceita_adiamento(self):
        # É a despedida ("vou parar de te chamar") — não tem o que adiar.
        ultimo = cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches[-1]
        assert ultimo.aceita_adiamento is False

    def test_em_atencao_aceita_adiamento_mesmo_sem_template(self):
        # 41:40 é literal sobre a fase de atenção: "essa mensagem pode ser com o
        # botão: ainda tenho estoque". Quem for criar o template tem de incluí-lo.
        toque = cj.cadencia_do_funil("reposicao_atacado", "em_atencao").touches[0]
        assert toque.aceita_adiamento is True


class TestOptOutReal:
    @pytest.mark.parametrize("texto", ["Não tenho interesse", "Parar mensagens",
                                       "nao tenho interesse", "parar mensagens"])
    def test_as_duas_frases_de_saida_sao_optout(self, texto):
        assert cj.classificar_resposta(texto) == cj.RESPOSTA_OPTOUT

    def test_o_optout_delega_para_is_optout_reply(self, monkeypatch):
        # Não reimplementamos a regra: `campaigns/worker.py::is_optout_reply` é a
        # única autoridade sobre o que conta como botão de saída (frozenset de duas
        # frases, igualdade normalizada). Duas cópias divergiriam no primeiro dia.
        from app.campaigns import worker
        chamadas = []

        def _fake(texto):
            chamadas.append(texto)
            return texto == "xyz"

        monkeypatch.setattr(worker, "is_optout_reply", _fake)
        assert cj.classificar_resposta("xyz") == cj.RESPOSTA_OPTOUT
        assert chamadas == ["xyz"]

    def test_texto_qualquer_nao_e_nem_optout_nem_adiamento(self):
        assert cj.classificar_resposta("quero comprar 50kg") is None

    def test_o_botao_de_saida_esta_em_todos_os_24_templates(self, botoes_por_template):
        from app.campaigns.worker import is_optout_reply
        for nome, botoes in botoes_por_template.items():
            assert botoes and is_optout_reply(botoes[-1]), nome


# ═══════════════════════════════════════════════════════════════════════════════
# 4. resolver_cadencia — o banco sobrepõe o código, vazio vale o código
# ═══════════════════════════════════════════════════════════════════════════════
class TestResolverCadencia:
    def test_sem_override_vale_o_codigo(self):
        assert cj.resolver_cadencia("reposicao_atacado", "reposicao") == \
            cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches

    @pytest.mark.parametrize("vazio", [None, {}, {"toques": {}}, {"toques": None}])
    def test_override_vazio_vale_o_codigo(self, vazio):
        # "Nasce vazia, e vazio = vale o código".
        assert cj.resolver_cadencia("reposicao_atacado", "reposicao", vazio) == \
            cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches

    def test_override_completo_vale_o_banco(self):
        overrides = {"toques": {
            1: {"dias": 1, "template_name": "t_um"},
            2: {"dias": 2, "template_name": "t_dois"},
            3: {"dias": 3, "template_name": "t_tres"},
            4: {"dias": 4, "template_name": "t_quatro"},
        }}
        toques = cj.resolver_cadencia("reposicao_atacado", "reposicao", overrides)
        assert [t.offset.days for t in toques] == [1, 2, 3, 4]
        assert [t.template_name for t in toques] == ["t_um", "t_dois", "t_tres", "t_quatro"]

    def test_override_parcial_mistura_na_chave_certa(self):
        # O requisito central da ata (33:28) na sua forma mais fina: João mexe em UM
        # toque e os outros continuam sendo o que o código diz.
        codigo = cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao", {"toques": {2: {"dias": 7}}}
        )
        assert toques[1].offset == timedelta(days=7)
        assert toques[1].template_name == codigo[1].template_name
        assert toques[0] == codigo[0]
        assert toques[2] == codigo[2]
        assert toques[3] == codigo[3]

    def test_override_so_de_template_nao_mexe_nos_dias(self):
        codigo = cj.cadencia_do_funil("atacado", "em_conversa").touches
        toques = cj.resolver_cadencia(
            "atacado", "em_conversa", {"toques": {5: {"template_name": "outro"}}}
        )
        assert toques[4].template_name == "outro"
        assert [t.offset for t in toques] == [t.offset for t in codigo]

    def test_valor_nulo_no_banco_vale_o_codigo(self):
        # Coluna NULL é "não sobrescrito", nunca "apague o que o código diz" — sem
        # isto, gravar só os dias apagaria o template do toque.
        codigo = cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao",
            {"toques": {1: {"dias": None, "template_name": None}}},
        )
        assert toques[0] == codigo[0]

    def test_chave_em_texto_funciona_igual(self):
        # O JSON que sobe do Postgres/PostgREST pode trazer a chave como string.
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao", {"toques": {"2": {"dias": 9}}}
        )
        assert toques[1].offset == timedelta(days=9)

    def test_nao_da_para_adicionar_toque_pelo_banco(self):
        # "Não editável: adicionar ou remover toques". É o que impede a tela de
        # virar builder de novo.
        toques = cj.resolver_cadencia(
            "atacado", "novo", {"toques": {2: {"dias": 5, "template_name": "x"}}}
        )
        assert len(toques) == 1

    def test_nao_da_para_remover_toque_pelo_banco(self):
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao",
            {"toques": {3: {"dias": None, "template_name": None}}},
        )
        assert len(toques) == 4

    def test_devolve_tupla(self):
        assert isinstance(cj.resolver_cadencia("atacado", "novo"), tuple)

    def test_resolver_nao_muta_o_codigo(self):
        antes = cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches
        cj.resolver_cadencia("reposicao_atacado", "reposicao", {"toques": {1: {"dias": 99}}})
        assert cj.cadencia_do_funil("reposicao_atacado", "reposicao").touches == antes
        assert antes[0].offset == timedelta(0)

    def test_codigo_desconhecido_levanta(self):
        with pytest.raises(KeyError):
            cj.resolver_cadencia("atacado", "inexistente")

    def test_funil_desconhecido_levanta(self):
        with pytest.raises(KeyError):
            cj.resolver_cadencia("varejo", "novo")

    def test_par_invalido_levanta(self):
        # "atacado" existe, "reposicao" existe, mas juntos não formam um par válido
        # — Atacado não tem cadência de Reposição.
        with pytest.raises(KeyError):
            cj.resolver_cadencia("atacado", "reposicao")


class TestResolverCadenciaCompleta:
    def test_o_gatilho_tambem_e_sobreposto(self):
        # 33:28 — "45 dias, mas opção do João editar o número de dias". É ESTE campo
        # que a frase da ata nomeia.
        assert cj.resolver("reposicao_atacado", "reposicao",
                            {"gatilho_dias": 60}).gatilho_dias == 60

    def test_gatilho_sem_override_vale_o_codigo(self):
        assert cj.resolver("reposicao_atacado", "reposicao", {}).gatilho_dias == 45

    def test_gatilho_nulo_vale_o_codigo(self):
        assert cj.resolver("reposicao_atacado", "reposicao",
                            {"gatilho_dias": None}).gatilho_dias == 45

    def test_ativa_vem_do_banco(self):
        assert cj.resolver("reposicao_atacado", "reposicao",
                            {"ativa": True}).ativa is True

    def test_a_resolvida_carrega_o_que_o_agendador_precisa(self):
        r = cj.resolver("reposicao_private_label", "reposicao", {})
        assert r.codigo == "reposicao"
        assert r.funil == "reposicao_private_label"
        assert r.job_type == "joao_reposicao"
        assert r.pipeline_id == PIPELINES["reposicao_private_label"]
        assert r.gatilho_stage_key == "novo"
        assert r.gatilho_stage_rotulo == "Cliente Ativo"
        assert r.touches == cj.cadencia_do_funil("reposicao_private_label", "reposicao").touches

    def test_a_resolvida_e_congelada(self):
        with pytest.raises(FrozenInstanceError):
            cj.resolver("atacado", "novo", {}).ativa = True

    def test_funil_desconhecido_levanta(self):
        with pytest.raises(KeyError):
            cj.resolver("varejo", "novo", {})

    def test_par_invalido_levanta(self):
        with pytest.raises(KeyError):
            cj.resolver("atacado", "reposicao", {})


class TestValidacaoDosToques:
    """O que a API precisa recusar ANTES de gravar."""

    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_a_cadencia_do_codigo_e_valida(self, funil_codigo, codigo):
        assert cj.validar_toques(cj.resolver_cadencia(funil_codigo, codigo)) == ()

    def test_recusa_dias_negativos(self):
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao", {"toques": {2: {"dias": -1}}}
        )
        assert cj.validar_toques(toques)

    def test_recusa_ordem_invertida(self):
        # Toque 3 antes do toque 2 faria a cadência sair fora de ordem — o lead
        # receberia a despedida antes da oferta.
        toques = cj.resolver_cadencia(
            "reposicao_atacado", "reposicao", {"toques": {3: {"dias": 1}}}
        )
        problemas = cj.validar_toques(toques)
        assert problemas and any("3" in p for p in problemas)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. "Em atenção" repete até o lead dizer que não quer
# ═══════════════════════════════════════════════════════════════════════════════
class TestRepeticaoDeEmAtencao:
    @pytest.mark.parametrize("funil_codigo,codigo", PARES)
    def test_so_em_atencao_repete(self, funil_codigo, codigo):
        cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
        assert cadencia.repete_ultimo is (codigo == "em_atencao")

    def test_o_intervalo_de_repeticao_e_de_tres_dias(self):
        # 38:08 — "uma mensagem a cada três dias até ele falar que não quer mais".
        assert cj.resolver("reposicao_atacado", "em_atencao", {}).intervalo_repeticao \
            == timedelta(days=3)

    @pytest.mark.parametrize("funil_codigo,codigo",
                              [p for p in PARES if p[1] != "em_atencao"])
    def test_cadencia_que_termina_nao_tem_intervalo(self, funil_codigo, codigo):
        assert cj.resolver(funil_codigo, codigo, {}).intervalo_repeticao is None

    def test_o_intervalo_acompanha_o_override_de_dias(self):
        # É por isso que o intervalo é o OFFSET do toque que repete, e não um campo à
        # parte: assim "a cada quantos dias" já é editável pelos mesmos `dias` do
        # toque, sem inventar uma quinta coluna fora do que o spec permite.
        r = cj.resolver("reposicao_atacado", "em_atencao", {"toques": {1: {"dias": 5}}})
        assert r.intervalo_repeticao == timedelta(days=5)

    def test_intervalo_zero_para_a_cadencia_em_vez_de_repetir(self):
        # Fail-safe do "a cada 0 dias": se alguém gravar 0 no toque que repete, o
        # motor não pode receber um intervalo que o faria reenviar em laço. Devolver
        # None faz a cadência PARAR depois do toque — falha para o lado silencioso,
        # não para o lado que bombardeia o cliente.
        r = cj.resolver("reposicao_atacado", "em_atencao", {"toques": {1: {"dias": 0}}})
        assert r.intervalo_repeticao is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. A migration (texto — a suíte não tem banco)
# ═══════════════════════════════════════════════════════════════════════════════
class TestMigrationCabecalho:
    def test_o_arquivo_existe_no_lugar_certo(self):
        assert SQL_PATH.exists()
        assert SQL_PATH.parent.name == "migrations"

    def test_avisa_que_nao_e_aplicada_pelo_deploy(self, sql):
        cabecalho = sql[:2500]
        assert "NAO E APLICADA PELO DEPLOY" in cabecalho
        assert "SQL editor do Supabase" in cabecalho
        assert "revisada por um humano" in cabecalho
        assert "Nenhum agente de IA" in cabecalho

    def test_aponta_para_o_spec_do_funil(self, sql):
        # A forma atual (funil-primeiro) é governada pelo spec de 21/09 — é ele que
        # esta migration implementa.
        assert "2026-09-21-followup-funil-por-funil-design.md" in sql[:3000]

    def test_declara_que_a_tabela_nasce_vazia(self, sql):
        assert "vazia" in sql.lower()

    def test_diz_que_reexecutar_e_seguro(self, sql):
        assert "Reexecutar" in sql


class TestMigrationCriaAsDuasTabelas:
    def test_cria_a_tabela_de_toques(self, sql_codigo):
        assert re.search(r"CREATE TABLE IF NOT EXISTS\s+followup_joao_toque",
                         sql_codigo, re.I)

    def test_cria_a_tabela_de_cadencia(self, sql_codigo):
        assert re.search(r"CREATE TABLE IF NOT EXISTS\s+followup_joao_cadencia",
                         sql_codigo, re.I)

    def test_a_chave_do_toque_e_funil_cadencia_toque(self, sql_codigo):
        assert re.search(r"PRIMARY KEY\s*\(\s*funil\s*,\s*cadencia\s*,\s*toque\s*\)",
                         sql_codigo, re.I)

    def test_a_chave_da_cadencia_e_funil_cadencia(self, sql_codigo):
        assert re.search(r"PRIMARY KEY\s*\(\s*funil\s*,\s*cadencia\s*\)",
                         sql_codigo, re.I)

    def test_nao_tem_mais_coluna_linha(self, sql_codigo):
        # A coluna `linha` some: `funil` já carrega essa distinção — manter as duas
        # seria duas colunas dizendo a mesma coisa.
        assert not re.search(r"\blinha\b", sql_codigo, re.I)

    @pytest.mark.parametrize("coluna", ["dias", "template_name"])
    def test_dias_e_template_name_sao_opcionais(self, sql_codigo, coluna):
        # NULL é o que significa "vale o código". Um NOT NULL aqui obrigaria a tela a
        # gravar o valor do código junto — e o código deixaria de ser a origem.
        linha = re.search(rf"^\s*{coluna}\s+\w+.*$", sql_codigo, re.I | re.M)
        assert linha, coluna
        assert "NOT NULL" not in linha.group(0).upper(), linha.group(0)

    def test_gatilho_dias_e_ativa_sao_por_funil_e_cadencia(self, sql_codigo):
        bloco = re.search(
            r"CREATE TABLE IF NOT EXISTS\s+followup_joao_cadencia(.*?);",
            sql_codigo, re.I | re.S,
        )
        assert bloco
        assert "gatilho_dias" in bloco.group(1)
        assert "ativa" in bloco.group(1)
        assert "toque" not in bloco.group(1)

    def test_gatilho_dias_nao_mora_na_tabela_de_toque(self, sql_codigo):
        bloco = re.search(
            r"CREATE TABLE IF NOT EXISTS\s+followup_joao_toque(.*?);",
            sql_codigo, re.I | re.S,
        )
        assert bloco
        assert "gatilho_dias" not in bloco.group(1)


class TestMigrationNaoDeixaAdicionarToque:
    """A trava estrutural, do lado do banco: a tabela é sobreposição, não um
    builder. Sem o CHECK, um INSERT com toque=9 na cadência "Novo" seria aceito
    pelo banco e ignorado em silêncio pelo código."""

    @pytest.mark.parametrize("codigo", CODIGOS)
    def test_o_check_limita_o_numero_do_toque_ao_que_a_cadencia_tem(self, sql_codigo, codigo):
        n = len(OFFSETS[codigo])
        trecho = re.search(rf"cadencia = '{codigo}'[^)]*", sql_codigo)
        assert trecho, codigo
        assert str(n) in trecho.group(0), (codigo, trecho.group(0))

    def test_o_check_lista_as_quatro_cadencias(self, sql_codigo):
        for codigo in CODIGOS:
            assert f"'{codigo}'" in sql_codigo

    def test_o_check_lista_os_funis_com_cadencia(self, sql_codigo):
        for funil_codigo in ("atacado", "private_label", "reposicao_atacado",
                              "reposicao_private_label"):
            assert f"'{funil_codigo}'" in sql_codigo

    def test_recuperacao_nao_aparece_como_funil_valido_no_check(self, sql_codigo):
        # Zero cadência = zero linha aceita: "recuperacao" não deveria precisar
        # aparecer como valor aceito em nenhum CHECK.
        assert not re.search(r"funil\s*=\s*'recuperacao'", sql_codigo, re.I)

    def test_tem_check_de_toque_positivo(self, sql_codigo):
        assert re.search(r"toque\s*>=?\s*[01]", sql_codigo)


class TestMigrationParFunilCadenciaBateComOCodigo:
    """O teste que impede o código (`cadence_joao.FUNIS`) e o banco (o CHECK
    `followup_joao_cadencia_par_valido`) de divergir silenciosamente."""

    def test_cada_funil_do_codigo_aceita_exatamente_as_cadencias_que_ele_declara(
        self, sql_codigo,
    ):
        esperado = {
            f.codigo: sorted(c.codigo for c in f.cadencias)
            for f in cj.FUNIS
            if f.cadencias
        }
        for funil_codigo, codigos_esperados in esperado.items():
            padrao = (
                rf"funil\s*=\s*'{funil_codigo}'\s+AND\s+cadencia\s+IN\s*\(([^)]*)\)"
            )
            m = re.search(padrao, sql_codigo, re.I)
            assert m, funil_codigo
            no_sql = sorted(
                trecho.strip().strip("'") for trecho in m.group(1).split(",")
            )
            assert no_sql == codigos_esperados, (funil_codigo, no_sql, codigos_esperados)

    def test_recuperacao_no_codigo_tambem_nao_tem_cadencia(self):
        # O espelho, do lado do código: se algum dia `recuperacao` ganhar uma
        # cadência, o teste acima muda de comportamento sozinho (o `if f.cadencias`
        # passa a incluí-la) — só falha aqui se o par não existir também no SQL.
        assert cj.funil("recuperacao").cadencias == ()


class TestMigrationNasceVazia:
    def test_nao_tem_insert(self, sql_codigo):
        # "Nasce vazia" é literal: semear a tabela com os valores do código faria o
        # banco virar a origem, e um redeploy passaria a brigar com a tela.
        assert not re.search(r"\bINSERT\s+INTO\b", sql_codigo, re.I)

    @pytest.mark.parametrize("comando", [r"DROP\s+TABLE", r"TRUNCATE", r"DELETE\s+FROM"])
    def test_nao_tem_comando_destrutivo(self, sql_codigo, comando):
        assert not re.search(comando, sql_codigo, re.I), comando

    def test_nao_toca_em_outras_tabelas(self, sql_codigo):
        alvos = set(re.findall(
            r"(?:CREATE TABLE(?: IF NOT EXISTS)?|ALTER TABLE)\s+(\w+)", sql_codigo, re.I
        ))
        assert alvos <= {"followup_joao_toque", "followup_joao_cadencia"}, alvos

    def test_nao_mexe_em_follow_up_jobs(self, sql_codigo):
        # O caminho `standard` da ValerIA é o único follow-up que funciona em
        # produção (8.140 jobs). Esta migration não encosta nele.
        assert "follow_up_jobs" not in sql_codigo


class TestMigrationReexecutavel:
    def test_toda_criacao_e_if_not_exists(self, sql_codigo):
        criacoes = re.findall(r"CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX)\s+(IF NOT EXISTS)?",
                              sql_codigo, re.I)
        assert criacoes
        for tipo, guarda in criacoes:
            assert guarda, tipo

    def test_as_policies_sao_recriadas_com_drop_antes(self, sql_codigo):
        assert len(re.findall(r"DROP POLICY IF EXISTS", sql_codigo, re.I)) == \
            len(re.findall(r"CREATE POLICY", sql_codigo, re.I))


class TestMigrationSeguranca:
    @pytest.mark.parametrize("tabela", ["followup_joao_toque", "followup_joao_cadencia"])
    def test_liga_rls_nas_duas_tabelas(self, sql_codigo, tabela):
        assert re.search(
            rf"ALTER TABLE\s+{tabela}\s+ENABLE ROW LEVEL SECURITY", sql_codigo, re.I
        ), tabela

    def test_recarrega_o_cache_do_postgrest(self, sql_codigo):
        # Sem isto o PostgREST responde PGRST205 para tabela nova, e a tela abre
        # vazia sem erro visível.
        assert "NOTIFY pgrst" in sql_codigo


class TestNaoInvadeOTerritorioDaOutraTask:
    def test_a_task_f1_nao_escreve_no_scheduler(self):
        # Disciplina do plano: F1/F2/F3/F4 rodam disjuntos POR ARQUIVO. O handler
        # (`_process_joao_touch`) é do scheduler; este módulo só declara.
        assert "scheduler" not in MODULO.read_text(encoding="utf-8").lower()

    @pytest.mark.parametrize("proibido", ["get_supabase", "httpx", "requests", "async def"])
    def test_o_modulo_nao_faz_io(self, proibido):
        # Config-as-code, igual `cadence.py`: função pura, sem Supabase, sem rede.
        assert proibido not in MODULO.read_text(encoding="utf-8")

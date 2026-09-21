# backend/tests/test_sql_apaga_esteiras_joao_2026_09_18.py
"""Guarda-rails do SQL que apaga as 6 esteiras-campanha do João (18/09/2026).

Contexto: as três cadências do João foram montadas como CAMPANHAS do builder
(`campaigns`/`campaign_nodes`, supabase/migrations/20260527_automation_campaigns_schema.sql),
semeadas a cada start da API por `app/campaigns/esteiras_joao.py`. Esse caminho
foi abandonado por um motivo concreto: a esteira de Reposição morre no primeiro
toque. A ata manda mover o card ao tocar, e `automation/engine.py::_guard_broken`
cancela a matrícula quando o card sai da coluna que o gatilho vigia — o motor não
distingue "o vendedor moveu" de "a própria esteira moveu". O follow-up do João
passou a rodar no scheduler que já existe, como novos `job_type` em
`follow_up_jobs` (docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md).

Duas metades da mesma correção, e nenhuma funciona sozinha:

  1. o SEED saiu do código (módulo apagado + chamada removida de `app/main.py`) —
     sem isso as 6 campanhas voltariam no próximo deploy;
  2. este SQL apaga as 6 linhas que o seed já criou.

Por isso `TestOSeedSaiuDoCodigo` mora aqui, ao lado dos testes do texto do SQL:
é a metade que a suíte consegue verificar de verdade.

A suíte não tem banco — os scripts corretivos deste repo são aplicados à mão no
Supabase (o GitHub Actions só sobe imagem, nunca roda SQL). Sobre o SQL em si o
único guarda-rail possível é o TEXTO do arquivo, mesmo padrão de
test_sql_campanhas_teste_2026_09_16.py e test_sql_cards_extraviados_2026_09_16.py.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SQL_PATH = RAIZ / "scripts" / "apaga_esteiras_joao.sql"
MAIN_PY = RAIZ / "backend" / "app" / "main.py"
SEED_APAGADO = RAIZ / "backend" / "app" / "campaigns" / "esteiras_joao.py"
SEED_GENERICO = RAIZ / "backend" / "app" / "campaigns" / "esteiras.py"

# Os 6 nomes EXATOS gravados em `campaigns.name` pelo seed que foi apagado, na
# mesma ordem em que ele os declarava (ESTEIRAS_JOAO). O travessão é EM DASH
# (U+2014), não hífen — é o que está no banco.
NOMES_JOAO = [
    "Esteira Joao — Novo (Atacado)",
    "Esteira Joao — Novo (Private Label)",
    "Esteira Joao — Em conversa (Atacado)",
    "Esteira Joao — Em conversa (Private Label)",
    "Esteira Joao — Reposicao (Atacado)",
    "Esteira Joao — Reposicao (Private Label)",
]

# As 4 esteiras GENÉRICAS (`app/campaigns/esteiras.py`), que valem para qualquer
# instalação e FICAM. Elas começam com "Esteira — " — a colisão de prefixo que
# torna qualquer `LIKE 'Esteira%'` inaceitável neste script.
NOMES_GENERICOS = [
    "Esteira — Novo sem resposta nossa",
    "Esteira — Novo, lead sumiu",
    "Esteira — Reposicao",
    "Esteira — Follow-up de proposta",
]


def _sem_comentarios(texto: str) -> str:
    """Remove comentários `--` linha a linha.

    Importa para os testes que buscam comandos SQL executáveis (DELETE/DROP/
    TRUNCATE/...): o cabeçalho deste arquivo EXPLICA o desenho em português,
    citando esses mesmos termos, e um `in sql` cru leria a explicação como se
    fosse o comando.
    """
    return "\n".join(linha.split("--", 1)[0] for linha in texto.splitlines())


def _listas_in(codigo: str) -> list[list[str]]:
    """Os nomes de cada bloco `name IN (...)`, na ordem em que aparecem.

    O regex tolera UM nível de parênteses aninhados de propósito: os nomes reais
    contêm "(Atacado)" / "(Private Label)", e um `[^)]*` ingênuo cortaria a
    lista no primeiro nome.
    """
    blocos = re.findall(
        r"name\s+IN\s*\(((?:[^()]|\([^()]*\))*)\)", codigo, re.IGNORECASE
    )
    return [re.findall(r"'([^']*)'", bloco) for bloco in blocos]


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), (
        f"script que apaga as esteiras do João não encontrado em {SQL_PATH}"
    )
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codigo(sql) -> str:
    """O SQL sem comentários — para testes que procuram comandos, não prosa."""
    return _sem_comentarios(sql)


@pytest.fixture(scope="module")
def codigo_lower(codigo) -> str:
    return codigo.lower()


class TestArquivoExiste:
    def test_o_arquivo_existe(self):
        assert SQL_PATH.exists()


class TestAvisoDeSeguranca:
    """Mesmo contrato dos outros scripts de escrita em produção deste repo
    (scripts/apaga_campanhas_de_teste.sql,
    scripts/corrige_cards_reposicao_extraviados.sql): apaga linha em PRODUÇÃO,
    então precisa avisar antes de qualquer SQL executável."""

    def test_avisa_que_nao_pode_ser_executado_sem_autorizacao(self, sql):
        cabecalho = sql[:2000]
        assert "NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO" in cabecalho
        assert "Nenhum agente de IA deve rodar" in cabecalho
        assert "PRODUÇÃO" in cabecalho

    def test_declara_a_medicao_de_matriculas_e_a_data(self, sql):
        # Medido por leitura em produção em 16/09/2026 (o mesmo levantamento que
        # embasou scripts/apaga_campanhas_de_teste.sql), não de cabeça.
        assert "0 matrículas" in sql
        assert "16/09/2026" in sql

    def test_explica_por_que_as_esteiras_estao_sendo_apagadas(self, sql):
        # Sem o "porquê" no arquivo, quem revisa daqui a um mês não tem como
        # decidir se ainda faz sentido aplicar.
        assert "_guard_broken" in sql
        assert "follow_up" in sql


class TestSeletorPorNomeExato:
    """O WHERE tem que casar só os 6 nomes exatos. Um `LIKE 'Esteira%'` pegaria
    as 4 esteiras genéricas, que FICAM."""

    @pytest.mark.parametrize("nome", NOMES_JOAO)
    def test_cita_cada_nome_exato(self, sql, nome):
        assert f"'{nome}'" in sql

    def test_sao_seis_nomes_e_os_mesmos_em_todo_bloco_in(self, codigo):
        listas = _listas_in(codigo)
        assert listas, "não encontrei `name IN (...)` no script"
        do_joao = [l for l in listas if any("Joao" in n for n in l)]
        # Conferência ANTES, guarda DO, DELETE e conferência DEPOIS: quatro
        # blocos, e os quatro têm que listar exatamente os mesmos 6 nomes — uma
        # divergência entre a guarda e o DELETE apagaria fora do que foi conferido.
        assert len(do_joao) == 4, [len(l) for l in listas]
        for lista in do_joao:
            assert lista == NOMES_JOAO, lista

    def test_usa_em_dash_e_nao_hifen(self, sql):
        # "Esteira Joao - Novo" (hífen) não casaria linha nenhuma: o seed gravou
        # U+2014. O erro seria silencioso — 0 linhas apagadas, nenhum aviso.
        assert "Esteira Joao — " in sql
        assert "Esteira Joao - " not in sql

    def test_nao_usa_like_ou_ilike(self, codigo_lower):
        assert not re.search(r"\bi?like\b", codigo_lower)

    def test_filtra_por_status_draft(self, codigo):
        assert "status = 'draft'" in codigo or "c.status = 'draft'" in codigo

    def test_guarda_ausencia_de_matricula(self, codigo_lower):
        assert "not exists" in codigo_lower
        assert "campaign_enrollments" in codigo_lower

    def test_a_guarda_de_matricula_vale_tambem_no_delete(self, codigo):
        # Não basta o NOT EXISTS existir em algum lugar do arquivo: ele tem que
        # estar DENTRO do DELETE. Se ficasse só no SELECT de conferência, uma
        # esteira que tivesse rodado seria apagada assim mesmo.
        delete = re.search(r"DELETE\s+FROM\s+campaigns.*?;", codigo, re.IGNORECASE | re.DOTALL)
        assert delete, "não encontrei o DELETE em campaigns"
        corpo = delete.group(0)
        assert re.search(r"NOT\s+EXISTS", corpo, re.IGNORECASE), corpo[:300]
        assert "campaign_enrollments" in corpo
        assert "'draft'" in corpo


class TestNaoTocaAsEsteirasGenericas:
    """`app/campaigns/esteiras.py` continua vivo e continua semeando — as 4
    campanhas dele não podem entrar no alvo por acidente de prefixo."""

    def test_o_delete_nao_menciona_nenhuma_esteira_generica(self, codigo):
        delete = re.search(r"DELETE\s+FROM\s+campaigns.*?;", codigo, re.IGNORECASE | re.DOTALL)
        assert delete
        for nome in NOMES_GENERICOS:
            assert nome not in delete.group(0), nome

    def test_o_seed_generico_continua_no_repo(self):
        assert SEED_GENERICO.exists(), (
            "esteiras.py (as 4 genéricas) foi apagado junto — não era o alvo"
        )

    def test_os_nomes_genericos_do_script_batem_com_o_seed(self):
        # Se o seed genérico renomear uma esteira, o SELECT de conferência
        # "DEPOIS" passaria a olhar para um nome que não existe mais e deixaria
        # de provar que elas sobreviveram.
        from app.campaigns import esteiras
        assert {e["name"] for e in esteiras.ESTEIRAS} == set(NOMES_GENERICOS)


class TestTransacional:
    def test_tem_begin_e_commit(self, codigo):
        assert re.search(r"\bBEGIN\s*;", codigo)
        assert re.search(r"\bCOMMIT\s*;", codigo)

    def test_begin_vem_antes_do_commit(self, codigo):
        assert codigo.index("BEGIN;") < codigo.rindex("COMMIT;")


class TestBlocoDeConferencia:
    def test_tem_select_de_conferencia_antes_do_begin(self, sql):
        i_begin = sql.index("BEGIN;")
        antes = sql[:i_begin]
        assert re.search(r"\bSELECT\b", antes, re.IGNORECASE)

    def test_conferencia_lista_nome_matriculas_e_env_tag(self, sql):
        i_begin = sql.index("BEGIN;")
        antes = sql[:i_begin].lower()
        assert "name" in antes
        assert "matricula" in antes   # cobre "matriculas"/"matrículas"
        assert "env_tag" in antes     # dev e produção compartilham o Supabase

    def test_tem_conferencia_depois_do_commit(self, sql):
        i_commit = sql.rindex("COMMIT;")
        assert re.search(r"\bSELECT\b", sql[i_commit:], re.IGNORECASE)


class TestAvisaSobreCascade:
    """Cuidado explícito: apagar `campaigns` cascateia em `campaign_nodes`
    (FK ON DELETE CASCADE) — quem revisa precisa saber disso ANTES de aplicar."""

    def test_menciona_campaign_nodes_e_cascade(self, sql):
        assert "campaign_nodes" in sql
        assert "CASCADE" in sql.upper()

    def test_declara_quantos_nos_caem_junto(self, sql):
        # 3 + 16 + 10 nós, vezes as duas linhas (Atacado / Private Label).
        assert "58 nós" in sql


class TestSemComandoDestrutivo:
    def test_nao_tem_drop(self, codigo):
        assert not re.search(r"\bDROP\b", codigo, re.IGNORECASE)

    def test_nao_tem_truncate(self, codigo):
        assert not re.search(r"\bTRUNCATE\b", codigo, re.IGNORECASE)

    def test_todo_delete_tem_where(self, codigo):
        deletes = re.findall(r"DELETE\s+FROM\s+\S+.*?;", codigo, re.IGNORECASE | re.DOTALL)
        assert deletes, "esperava pelo menos um DELETE"
        for stmt in deletes:
            assert re.search(r"\bWHERE\b", stmt, re.IGNORECASE), stmt[:200]

    def test_o_unico_delete_e_em_campaigns(self, codigo):
        tabelas = re.findall(r"DELETE\s+FROM\s+(\w+)", codigo, re.IGNORECASE)
        assert tabelas == ["campaigns"], tabelas

    def test_nao_tem_update_nenhum(self, codigo):
        assert not re.search(r"\bUPDATE\s+\w", codigo, re.IGNORECASE)

    def test_nao_mexe_em_outras_tabelas(self, codigo):
        for tabela in ("leads", "deals", "sales", "lead_tags", "follow_up_jobs",
                       "campaign_nodes", "campaign_enrollments"):
            assert not re.search(
                rf"(DELETE\s+FROM|UPDATE)\s+{tabela}\b", codigo, re.IGNORECASE
            ), tabela


class TestGuardaDeSanidade:
    """A transação inteira aborta se o alvo não bater com o esperado — não
    apaga campanha nenhuma "pela metade" nem além do previsto."""

    def test_aborta_se_alvo_vazio(self, codigo):
        assert "RAISE EXCEPTION" in codigo
        assert re.search(r"alvo\s*=\s*0", codigo)

    def test_aborta_se_alvo_passar_de_seis(self, codigo):
        # Teto por "maior que" (e não igualdade, como em
        # apaga_campanhas_de_teste.sql): uma segunda passada legítima acharia
        # menos de 6 e não deve travar. Mais de 6 significa que o WHERE casou
        # algo que não são as seis esteiras — aí trava.
        assert re.search(r"alvo\s*>\s*6", codigo), (
            "sem esse teto, um WHERE que passe a casar mais campanhas apagaria "
            "mais do que as 6 esteiras do João"
        )


class TestNaoEhMigration:
    def test_nao_vive_em_supabase_migrations(self):
        assert SQL_PATH.parent.name != "migrations"

    def test_explica_por_que_nao_e_migration(self, sql):
        assert "NÃO É MIGRATION" in sql.upper()
        assert "supabase/migrations" in sql

    def test_diz_que_e_aplicado_a_mao_apos_revisao(self, sql):
        assert "à mão" in sql
        assert "revisão" in sql


class TestOSeedSaiuDoCodigo:
    """A outra metade da correção. Só apagar as linhas do banco não resolve:
    `seed_esteiras_joao` rodava a cada start da API e recriava as 6 campanhas.
    Se alguém reintroduzir o seed, este SQL vira teatro — e é este teste que
    avisa, não o banco."""

    def test_o_modulo_do_seed_nao_existe_mais(self):
        assert not SEED_APAGADO.exists(), (
            "app/campaigns/esteiras_joao.py voltou — as 6 campanhas seriam "
            "recriadas no próximo start da API, e apaga_esteiras_joao.sql "
            "passaria a ser inútil"
        )

    def test_o_modulo_do_seed_nao_e_importavel(self):
        import importlib.util
        assert importlib.util.find_spec("app.campaigns.esteiras_joao") is None

    def test_o_startup_nao_chama_mais_o_seed(self):
        fonte = MAIN_PY.read_text(encoding="utf-8")
        assert "seed_esteiras_joao" not in fonte
        assert "app.campaigns.esteiras_joao" not in fonte

    def test_o_startup_continua_chamando_o_seed_generico(self):
        # A remoção tinha alvo. Se o seed das 4 genéricas caiu junto, foi engano.
        fonte = MAIN_PY.read_text(encoding="utf-8")
        assert "seed_esteiras" in fonte
        assert "from app.campaigns.esteiras import seed_esteiras" in fonte

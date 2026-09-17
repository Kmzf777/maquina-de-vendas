# backend/tests/test_sql_campanhas_teste_2026_09_16.py
"""Guarda-rails do SQL que apaga as 3 campanhas de lixo de teste (16/09/2026).

Contexto: o sistema de automação de campanhas (`campaigns` / `campaign_nodes` /
`campaign_enrollments`, supabase/migrations/20260527_automation_campaigns_schema.sql)
tem 16 campanhas no banco, medido em produção em 16/09/2026 — 0 com
status='active' e ZERO matrículas (`campaign_enrollments`) em toda a história:
nenhuma das 16 nunca rodou para lead nenhum. Três são lixo de teste:

    Tiburcio-Miranda-2       status='draft'   6 nós
    cadencia                 status='draft'   3 nós
    Cadencia Teste deletar   status='draft'   1 nó

As outras 13 são seeds legítimos (esteiras genéricas, esteiras do João, espelho
da ValerIA) e não podem ser tocadas — daí o WHERE ter que casar pelos 3 nomes
EXATOS, nunca um padrão (`LIKE`/`ILIKE`) que pudesse pegar uma campanha real
cujo nome contivesse "teste" ou "cadência".

A suíte não tem banco — os scripts corretivos deste repo são aplicados à mão no
Supabase (o GitHub Actions só sobe imagem, nunca roda SQL). Aqui o único
guarda-rail possível é sobre o TEXTO do arquivo, mesmo padrão de
test_sql_cards_extraviados_2026_09_16.py e de
test_recuperacao_migration_2026_09_09.py::TestCorretivoDosDealsExtraviados.
"""
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SQL_PATH = RAIZ / "scripts" / "apaga_campanhas_de_teste.sql"

NOME_1 = "Tiburcio-Miranda-2"
NOME_2 = "cadencia"
NOME_3 = "Cadencia Teste deletar"


def _sem_comentarios(texto: str) -> str:
    """Remove comentários `--` linha a linha.

    Importa para os testes que buscam comandos SQL executáveis (DELETE/DROP/
    TRUNCATE/...): o cabeçalho deste arquivo EXPLICA o desenho em português,
    citando esses mesmos termos, e um `in sql` cru leria a explicação como se
    fosse o comando.
    """
    return "\n".join(linha.split("--", 1)[0] for linha in texto.splitlines())


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL_PATH.exists(), (
        f"script de limpeza das campanhas de teste não encontrado em {SQL_PATH}"
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
    (scripts/corrige_cards_reposicao_extraviados.sql,
    scripts/recuperacao/corrigir_deals_reposicao.sql): apaga linha em
    PRODUÇÃO, então precisa avisar antes de qualquer SQL executável.
    """

    def test_avisa_que_nao_pode_ser_executado_sem_autorizacao(self, sql):
        cabecalho = sql[:2000]
        assert "NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO" in cabecalho
        assert "Nenhum agente de IA deve rodar" in cabecalho
        assert "PRODUÇÃO" in cabecalho

    def test_declara_quantas_campanhas_existem_e_quantas_matriculas(self, sql):
        # Medido por leitura em produção em 16/09/2026, não de cabeça.
        assert "16 campanhas" in sql
        assert "0 matrículas" in sql
        assert "16/09/2026" in sql


class TestSeletorPorNomeExato:
    """O WHERE tem que casar só os 3 nomes exatos — nada de LIKE '%teste%',
    que pegaria qualquer uma das 13 campanhas legítimas cujo nome mencione
    "teste" ou "cadência"."""

    @pytest.mark.parametrize("nome", [NOME_1, NOME_2, NOME_3])
    def test_cita_cada_nome_exato(self, sql, nome):
        assert f"'{nome}'" in sql

    def test_sao_exatamente_tres_nomes_no_seletor(self, codigo):
        # As três strings citadas em um único IN (...) — não três blocos
        # soltos que poderiam divergir entre o DO de guarda e o DELETE.
        m = re.search(r"name\s+IN\s*\(([^)]*)\)", codigo, re.IGNORECASE)
        assert m, "não encontrei `name IN (...)` no script"
        nomes = re.findall(r"'([^']*)'", m.group(1))
        assert nomes == [NOME_1, NOME_2, NOME_3]

    def test_nao_usa_like_ou_ilike(self, codigo_lower):
        assert "like " not in codigo_lower and "like'" not in codigo_lower
        assert not re.search(r"\bi?like\b", codigo_lower)

    def test_filtra_por_status_draft(self, codigo):
        assert "status = 'draft'" in codigo or "c.status = 'draft'" in codigo

    def test_guarda_ausencia_de_matricula(self, codigo_lower):
        assert "not exists" in codigo_lower
        assert "campaign_enrollments" in codigo_lower


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

    def test_conferencia_lista_nome_e_matriculas(self, sql):
        i_begin = sql.index("BEGIN;")
        antes = sql[:i_begin].lower()
        assert "name" in antes
        assert "matricula" in antes  # cobre "matriculas"/"matrículas"


class TestAvisaSobreCascade:
    """Cuidado explícito: apagar `campaigns` cascateia em `campaign_nodes`
    (FK ON DELETE CASCADE) — quem revisa precisa saber disso ANTES de aplicar."""

    def test_menciona_campaign_nodes_e_cascade(self, sql):
        assert "campaign_nodes" in sql
        assert "CASCADE" in sql.upper()


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

    def test_nao_mexe_em_outras_tabelas(self, codigo):
        # Nada de leads/deals/tags — o alvo é só campaigns (campaign_nodes cai
        # por cascata, não por um comando explícito deste script).
        for tabela in ("leads", "deals", "sales", "lead_tags"):
            assert not re.search(rf"(DELETE\s+FROM|UPDATE)\s+{tabela}\b", codigo, re.IGNORECASE), tabela


class TestGuardaDeSanidade:
    """A transação inteira aborta se o alvo não bater com o esperado — não
    apaga campanha nenhuma "pela metade" nem além do previsto."""

    def test_aborta_se_alvo_vazio(self, codigo):
        assert "RAISE EXCEPTION" in codigo
        assert re.search(r"alvo\s*=\s*0", codigo)

    def test_aborta_se_alvo_diferente_de_tres(self, codigo):
        # Teto por igualdade (não por "maior que"): são exatamente 3 campanhas
        # de teste conhecidas — qualquer contagem diferente merece revisão.
        assert re.search(r"alvo\s*(<>|!=)\s*3", codigo), (
            "sem esse teto, um WHERE que passe a casar mais campanhas apagaria mais do que as 3 conhecidas"
        )


class TestNaoEhMigration:
    def test_nao_vive_em_supabase_migrations(self):
        assert SQL_PATH.parent.name != "migrations"

    def test_explica_por_que_nao_e_migration(self, sql):
        assert "migration" in sql.lower()

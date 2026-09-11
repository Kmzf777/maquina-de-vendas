"""Guardas da migration `20260911_cadencias_reentrada.sql`.

Asserts no TEXTO do SQL: a migration nao roda no deploy (e aplicada a mao no editor do
Supabase) e a suite nao tem banco. Mesmo padrao de test_esteiras_migration_sql.py.

O que esta migration conserta: `UNIQUE (campaign_id, lead_id)` SEM clausula parcial
impedia o lead de entrar numa campanha mais de uma vez NA VIDA — assim que a matricula
virava 'completed', create_enrollment colidia. Fatal para a esteira de reposicao, cujo
desenho e repetir a cada 45 dias.
"""
import pathlib
import re

SQL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260911_cadencias_reentrada.sql"
)


def _sem_comentario() -> str:
    """SQL sem os `--` e com espacos normalizados.

    Tirar os comentarios importa: o arquivo explica cada decisao em portugues logo acima
    dela, e um assert de texto casaria com a EXPLICACAO em vez de com o codigo.
    """
    txt = SQL.read_text(encoding="utf-8")
    limpo = "\n".join(l.split("--")[0] for l in txt.splitlines())
    return re.sub(r"\s+", " ", limpo).strip()


def test_arquivo_existe():
    assert SQL.exists(), f"migration nao encontrada em {SQL}"


def test_derruba_a_constraint_total_por_nome():
    """E a UNIQUE sem clausula parcial que impede o lead de reentrar na vida."""
    sql = _sem_comentario()
    assert re.search(
        r"DROP CONSTRAINT IF EXISTS campaign_enrollments_campaign_id_lead_id_key", sql
    ), "a migration nao derruba a constraint total pelo nome"


def test_nao_derruba_o_indice_parcial():
    """O parcial protege o que importa — matricula VIVA duplicada. Derruba-lo permitiria
    duas matriculas ativas do mesmo lead na mesma esteira."""
    sql = _sem_comentario()
    assert "DROP INDEX" not in sql, "a migration nao pode derrubar indice nenhum"
    assert "uq_campaign_enrollments_active" not in sql, (
        "a migration nao deve sequer mencionar o indice parcial em comando"
    )


def test_mexe_apenas_em_campaign_enrollments():
    """Escopo: uma tabela, um comando. Qualquer outra tabela aqui e acidente."""
    sql = _sem_comentario()
    tabelas = set(re.findall(r"ALTER TABLE (\w+)", sql))
    assert tabelas == {"campaign_enrollments"}, f"mexe em tabelas demais: {tabelas}"


def test_e_idempotente():
    """Reexecutar nao pode quebrar — a migration roda a mao e pode ser repetida."""
    assert "IF EXISTS" in _sem_comentario()


def test_termina_com_notify_pgrst():
    """Sem isso o PostgREST serve o schema em cache e o CRM responde PGRST204/205."""
    txt = SQL.read_text(encoding="utf-8").rstrip()
    assert "NOTIFY pgrst" in txt
    resto = txt[txt.rindex("NOTIFY pgrst"):]
    assert ";" in resto and resto.split(";", 1)[1].strip() == "", (
        "existe instrucao depois do NOTIFY pgrst"
    )

import pathlib
import re

SQL = pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20260818_bling_integration.sql"


def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def test_migration_exists():
    assert SQL.exists(), "migration 20260818_bling_integration.sql nao encontrada"


def test_cria_todas_as_tabelas():
    sql = _sql().lower()
    for tabela in (
        "bling_credentials", "bling_products", "bling_contacts",
        "bling_payment_methods", "bling_sellers", "bling_sync_state",
        "bling_seller_map", "bling_webhook_events", "bling_jobs", "sale_items",
    ):
        assert f"create table if not exists {tabela}" in sql, tabela


def test_vinculo_lead_contato_e_unico():
    sql = _sql().lower()
    assert "alter table leads add column if not exists bling_contact_id bigint" in sql
    # UNIQUE parcial: e a garantia estrutural de 1:1 lead <-> contato Bling
    assert "create unique index" in sql and "leads_bling_contact_id_key" in sql
    assert "where bling_contact_id is not null" in sql


def test_pedido_bling_e_unico_em_sales():
    sql = _sql().lower()
    assert "sales_bling_order_id_key" in sql
    assert "unique index" in sql
    # UNIQUE parcial: sem o WHERE, o indice colide com todas as vendas legadas
    # (bling_order_id IS NULL) assim que a migration roda em producao.
    assert "where bling_order_id is not null" in sql


def test_seed_do_id_bling_vem_do_metadata():
    sql = _sql().lower()
    # os 1.208 leads da reativacao ja carregam metadata->>'id_bling'
    assert "metadata->>'id_bling'" in sql
    assert "~ '^[0-9]+$'" in sql
    # blindagem contra overflow de bigint (max 19 digitos): sem o limite de
    # tamanho, um valor sujo com 20+ digitos passa no regex, estoura o CAST e
    # aborta a migration inteira (o runner executa o arquivo como uma query so).
    assert "length(metadata->>'id_bling') <= 18" in sql


def test_vendas_legadas_viram_origin_manual():
    sql = _sql().lower()
    assert "update sales set origin = 'manual' where bling_order_id is null" in sql


def test_rls_ligado_em_todas_as_tabelas_novas():
    sql = _sql().lower()
    for tabela in (
        "bling_products", "bling_contacts", "bling_payment_methods",
        "bling_sellers", "bling_credentials", "bling_jobs",
        "bling_webhook_events", "sale_items",
    ):
        assert f"alter table {tabela} enable row level security" in sql, tabela


def test_credentials_nao_expoe_leitura_para_authenticated():
    """bling_credentials guarda refresh_token — so service_role le.

    Varre o arquivo inteiro (nao so o bloco de criacao da tabela): nenhuma
    statement CREATE POLICY que mencione bling_credentials pode conceder
    acesso a authenticated, onde quer que ela apareca no arquivo.
    """
    sql = _sql()
    policies = re.findall(r"CREATE POLICY.*?;", sql, flags=re.IGNORECASE | re.DOTALL)
    ofensoras = [
        p for p in policies
        if "bling_credentials" in p.lower() and "authenticated" in p.lower()
    ]
    assert not ofensoras, ofensoras

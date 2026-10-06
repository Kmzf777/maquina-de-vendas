"""Migração base da call de 01/10 (P0): contratos que P1-P7 consomem.

O CI não tem Postgres; aqui fixamos o texto. O comportamento dos triggers foi verificado
num Postgres 17 com o esquema de produção (ver plano, Task 0.2).
"""
from pathlib import Path

SQL = (
    Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20261006_call_semanal_base.sql"
).read_text(encoding="utf-8")


def test_colunas_ja_era_cliente():
    for col in ("ja_era_cliente boolean", "ja_era_cliente_fonte text",
                "ja_era_cliente_em timestamptz", "ja_era_cliente_por text"):
        assert f"add column if not exists {col}" in SQL


def test_regra_automatica_so_grava_true_e_nao_sobrescreve_vendedor():
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert "ja_era_cliente = true" in corpo
    assert "ja_era_cliente = false" not in SQL
    assert "l.ja_era_cliente is null" in corpo
    assert "::date < (l.created_at at time zone" in corpo
    assert "'cancelada'" in corpo


def test_trigger_nunca_derruba_a_venda():
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert "exception when others then" in corpo
    assert "raise warning" in corpo


def test_campanha_manual():
    for col in ("campanha_manual_canal", "campanha_manual_id", "campanha_manual_nome",
                "campanha_manual_por", "campanha_manual_em"):
        assert f"add column if not exists {col}" in SQL
    assert "in ('meta', 'google')" in SQL


def test_lead_events_vira_timeline():
    assert "add column if not exists occurred_at timestamptz not null default now()" in SQL
    assert "add column if not exists dedupe_key text" in SQL
    assert "lead_events_dedupe_key_uidx" in SQL
    assert "where dedupe_key is not null" in SQL


def test_arquivo_de_referrals_tem_trigger_e_backfill():
    assert "create table if not exists public.meta_referrals_arquivo" in SQL
    assert "trg_meta_webhook_logs_arquiva_referral" in SQL
    assert "$.entry[*].changes[*].value.messages[*]" in SQL
    assert "on conflict do nothing" in SQL


def test_view_primeira_origem():
    assert "create or replace view public.lead_primeira_origem" in SQL
    assert "e.event_type = 'entrada'" in SQL
    assert "order by e.lead_id, e.occurred_at asc" in SQL


def test_idempotente():
    assert "create table public." not in SQL  # sempre "if not exists"
    assert SQL.count("drop trigger if exists") == SQL.count("create trigger")


def test_arquivo_de_referrals_fechado_para_anon_e_authenticated():
    """Revisão: a ACL padrão do schema public dá arwdDxtm a anon/authenticated em toda
    tabela nova. Sem RLS + revoke, a anon key do browser leria o telefone de todo lead CTWA."""
    assert "alter table public.meta_referrals_arquivo enable row level security" in SQL
    assert "revoke all on public.meta_referrals_arquivo from anon, authenticated" in SQL
    for fn in ("fn_arquiva_meta_referrals(public.meta_webhook_logs)",
               "fn_meta_webhook_logs_arquiva_referral()",
               "fn_sales_marca_ja_era_cliente()"):
        assert f"revoke execute on function public.{fn} from public, anon, authenticated" in SQL


def test_view_primeira_origem_respeita_rls_e_nao_vaza_para_anon():
    assert "with (security_invoker = true)" in SQL
    assert "revoke all on public.lead_primeira_origem from anon" in SQL


def test_ja_era_cliente_compara_datas_no_fuso_de_sao_paulo():
    """sold_at do Bling é a data às 12:00 UTC; venda manual, 12:00 local. Comparar o
    instante marcaria como "já era cliente" quem chegou de manhã e comprou no mesmo dia."""
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert "new.sold_at < l.created_at" not in SQL
    assert ("(new.sold_at at time zone 'America/Sao_Paulo')::date"
            " < (l.created_at at time zone 'America/Sao_Paulo')::date") in corpo
    assert ("(s.sold_at at time zone 'America/Sao_Paulo')::date"
            " < (l.created_at at time zone 'America/Sao_Paulo')::date") in SQL


def test_guardas_baratas_ficam_fora_da_subtransacao():
    """Um bloco begin/exception abre subtransação a cada linha; o caminho que não faz nada
    não deve pagar isso (UPDATE em massa estoura o cache de subxid)."""
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert corpo.index("return new;") < corpo.index("exception when others")


def test_funcoes_rodam_como_dono_com_search_path_fixo():
    """Verificado no Postgres 17 com uma role sem privilégio: sem SECURITY DEFINER o
    trigger de arquivo chamava fn_arquiva_meta_referrals e levava 'permission denied'."""
    assert SQL.count("security definer set search_path = public, pg_temp") == 3

"""A migration de ad_conversions é aplicada à mão — o teste trava o contrato do SQL."""
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "supabase/migrations/20261008_ad_conversions.sql").read_text()


def test_tabela_fila_tem_dedupe_key_unica():
    assert "create table if not exists public.ad_conversions" in SQL.lower()
    assert "dedupe_key      text not null unique" in SQL


def test_status_e_etapas_fechados():
    for v in ("'pendente'", "'enviado'", "'erro'", "'fora_da_janela'", "'ignorado'"):
        assert v in SQL
    for v in ("'lead'", "'qualified'", "'opportunity'", "'purchase'"):
        assert v in SQL


def test_valores_estimados_sem_purchase():
    assert "create table if not exists public.ad_conversion_values" in SQL.lower()
    assert "check (stage in ('lead','qualified','opportunity'))" in SQL


def test_leads_ganham_gbraid_wbraid():
    assert "add column if not exists gbraid text" in SQL
    assert "add column if not exists wbraid text" in SQL


def test_trigger_de_entrada_ve_gbraid_wbraid():
    assert "'gbraid', new.gbraid" in SQL or "'gbraid', p_gbraid" in SQL
    assert "new.gbraid is not distinct from old.gbraid" in SQL


def test_nao_dropa_conversion_events():
    # o script de mesclagem (scripts/bling/mesclar_leads_duplicados.py) ainda a referencia
    assert "drop table" not in SQL.lower()


def test_rls_sem_policy_e_transacao():
    assert "enable row level security" in SQL.lower()
    assert SQL.strip().lower().startswith("--")
    assert "begin;" in SQL.lower() and "commit;" in SQL.lower()


def test_assinaturas_antigas_dropadas_antes_de_recriar():
    # sem o DROP ficariam duas sobrecargas e a chamada com 7/8 argumentos viraria ambígua
    for antiga in (
        "fn_lead_canal(text, text, text, text, text, text, text)",
        "fn_lead_tem_rastreio(text, text, text, text, text, text)",
        "fn_lead_entrada_metadata(text, text, text, text, text, text, text, text)",
    ):
        drop = f"drop function if exists public.{antiga};"
        assert drop in SQL
        assert SQL.index(drop) < SQL.index("create or replace function public.fn_lead_canal(")


def test_gbraid_wbraid_contam_como_google_ads_e_como_rastreio():
    canal = SQL.split("function public.fn_lead_canal(")[1].split("$$;")[0]
    assert "fn_lead_txt(p_gbraid) <> ''" in canal and "fn_lead_txt(p_wbraid) <> ''" in canal
    primeiro_when = canal.split("when")[1]
    assert "p_gbraid" in primeiro_when and "Google Ads" in canal.split("when")[1] + canal.split("when")[2]
    rastreio = SQL.split("function public.fn_lead_tem_rastreio(")[1].split("$$;")[0]
    assert "p_gbraid" in rastreio and "p_wbraid" in rastreio


def test_trigger_de_entrada_dispara_nas_colunas_novas_e_mantem_seguranca():
    assert "after insert or update of ctwa_clid, gclid, gbraid, wbraid, fbclid, meta_ad_id" in SQL
    corpo = SQL.split("function public.fn_lead_events_leads_entrada()")[1].split("end $$;")[0]
    assert "security definer set search_path = public, pg_temp" in SQL
    assert "exception when others then" in corpo
    assert "raise warning 'fn_lead_events_leads_entrada: %', sqlerrm" in corpo
    assert "revoke execute on function public.fn_lead_events_leads_entrada() from public, anon, authenticated;" in SQL


def test_sem_placeholder_do_plano():
    assert "(a) Recrie" not in SQL

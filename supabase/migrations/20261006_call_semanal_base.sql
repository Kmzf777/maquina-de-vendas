-- 20261006_call_semanal_base.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao, depois de revisada. Idempotente: pode rodar
--    de novo sem efeito colateral.
--
-- Base comum das pendencias da call de Ads de 01/10 (spec
-- docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md, pacote P0). Os pacotes
-- P1-P7 programam contra estes contratos:
--   1. leads.ja_era_cliente (+ fonte/em/por) e a regra automatica no banco;
--   2. leads.campanha_manual_* (atribuicao manual de campanha no /trafego);
--   3. lead_events vira a linha do tempo (occurred_at, source, dedupe_key);
--   4. meta_referrals_arquivo: copia permanente dos referrals CTWA (seguro contra a
--      retencao de 15 dias do meta_webhook_logs);
--   5. view lead_primeira_origem.

-- ── 1. "JA ERA CLIENTE" ─────────────────────────────────────────────────────
-- null = desconhecido. O sistema so grava TRUE (com evidencia); FALSE so vem de um humano.
alter table public.leads add column if not exists ja_era_cliente boolean;
alter table public.leads add column if not exists ja_era_cliente_fonte text;
alter table public.leads add column if not exists ja_era_cliente_em timestamptz;
alter table public.leads add column if not exists ja_era_cliente_por text;

do $$ begin
  alter table public.leads add constraint leads_ja_era_cliente_fonte_check
    check (ja_era_cliente_fonte is null or ja_era_cliente_fonte in ('auto', 'vendedor'));
exception when duplicate_object then null; end $$;

-- Evidencia: venda nao cancelada ANTERIOR a entrada do lead no CRM (ex.: pedido historico
-- do Bling). Cliente que so existia no WhatsApp fica null e o vendedor responde.
create or replace function public.fn_sales_marca_ja_era_cliente()
returns trigger language plpgsql as $$
begin
  begin
    if new.lead_id is not null
       and coalesce(new.status, 'registrada') <> 'cancelada'
       and new.sold_at is not null then
      update public.leads l
         set ja_era_cliente = true,
             ja_era_cliente_fonte = 'auto',
             ja_era_cliente_em = now()
       where l.id = new.lead_id
         and l.ja_era_cliente is null
         and new.sold_at < l.created_at;
    end if;
  exception when others then
    raise warning 'fn_sales_marca_ja_era_cliente: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_sales_marca_ja_era_cliente on public.sales;
create trigger trg_sales_marca_ja_era_cliente
  after insert or update of sold_at, status, lead_id on public.sales
  for each row execute function public.fn_sales_marca_ja_era_cliente();

-- Backfill: a mesma regra sobre as vendas que ja existem.
update public.leads l
   set ja_era_cliente = true,
       ja_era_cliente_fonte = 'auto',
       ja_era_cliente_em = now()
 where l.ja_era_cliente is null
   and exists (
     select 1 from public.sales s
      where s.lead_id = l.id
        and coalesce(s.status, 'registrada') <> 'cancelada'
        and s.sold_at < l.created_at
   );

-- ── 2. ATRIBUICAO MANUAL DE CAMPANHA ────────────────────────────────────────
-- Preenchida vence meta_ad_id/UTMs no relatorio de campanhas (P2).
alter table public.leads add column if not exists campanha_manual_canal text;
alter table public.leads add column if not exists campanha_manual_id text;
alter table public.leads add column if not exists campanha_manual_nome text;
alter table public.leads add column if not exists campanha_manual_por text;
alter table public.leads add column if not exists campanha_manual_em timestamptz;

do $$ begin
  alter table public.leads add constraint leads_campanha_manual_canal_check
    check (campanha_manual_canal is null or campanha_manual_canal in ('meta', 'google'));
exception when duplicate_object then null; end $$;

-- ── 3. LEAD_EVENTS = LINHA DO TEMPO ─────────────────────────────────────────
-- Tipos (event_type): entrada, etapa, venda, venda_cancelada, disparo, mesclagem,
-- atribuicao_manual. Payload em metadata. occurred_at = quando aconteceu (no backfill e
-- diferente de created_at). dedupe_key deterministica deixa o backfill idempotente.
alter table public.lead_events add column if not exists occurred_at timestamptz not null default now();
alter table public.lead_events add column if not exists source text;
alter table public.lead_events add column if not exists dedupe_key text;

create unique index if not exists lead_events_dedupe_key_uidx
  on public.lead_events (dedupe_key) where dedupe_key is not null;
create index if not exists lead_events_lead_occurred_idx
  on public.lead_events (lead_id, occurred_at desc);

-- ── 4. ARQUIVO DOS REFERRALS CTWA ───────────────────────────────────────────
-- Um referral por mensagem inbound que o trouxe. Fonte de P2 (recuperar meta_ad_id) e P3
-- (entradas historicas). Nao depende da retencao do log.
create table if not exists public.meta_referrals_arquivo (
  id uuid primary key default gen_random_uuid(),
  log_id uuid not null,
  received_at timestamptz not null,
  from_number text,
  ctwa_clid text,
  source_id text,
  source_type text,
  referral jsonb not null
);
create unique index if not exists meta_referrals_arquivo_log_ref_uidx
  on public.meta_referrals_arquivo (log_id, md5(referral::text));
create index if not exists meta_referrals_arquivo_ctwa_idx
  on public.meta_referrals_arquivo (ctwa_clid);
create index if not exists meta_referrals_arquivo_from_idx
  on public.meta_referrals_arquivo (from_number, received_at);

create or replace function public.fn_arquiva_meta_referrals(p_log public.meta_webhook_logs)
returns void language sql as $$
  insert into public.meta_referrals_arquivo
    (log_id, received_at, from_number, ctwa_clid, source_id, source_type, referral)
  select p_log.id,
         p_log.received_at,
         coalesce(m->>'from', p_log.from_number),
         m->'referral'->>'ctwa_clid',
         m->'referral'->>'source_id',
         m->'referral'->>'source_type',
         m->'referral'
    from jsonb_path_query(p_log.payload, '$.entry[*].changes[*].value.messages[*]') as m
   where m ? 'referral'
  on conflict do nothing;
$$;

create or replace function public.fn_meta_webhook_logs_arquiva_referral()
returns trigger language plpgsql as $$
begin
  begin
    if new.direction = 'inbound' and new.payload::text like '%"referral"%' then
      perform public.fn_arquiva_meta_referrals(new);
    end if;
  exception when others then
    raise warning 'fn_meta_webhook_logs_arquiva_referral: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_meta_webhook_logs_arquiva_referral on public.meta_webhook_logs;
create trigger trg_meta_webhook_logs_arquiva_referral
  after insert on public.meta_webhook_logs
  for each row execute function public.fn_meta_webhook_logs_arquiva_referral();

-- Backfill do que o log ainda guarda.
select public.fn_arquiva_meta_referrals(l)
  from public.meta_webhook_logs l
 where l.direction = 'inbound'
   and l.payload::text like '%"referral"%';

-- ── 5. PRIMEIRA ORIGEM ──────────────────────────────────────────────────────
-- Primeiro evento `entrada` de cada lead. metadata da entrada: canal, campanha_id,
-- campanha_nome (gravados pelo P3).
create or replace view public.lead_primeira_origem as
select distinct on (e.lead_id)
       e.lead_id,
       e.metadata->>'canal'         as canal,
       e.metadata->>'campanha_id'   as campanha_id,
       e.metadata->>'campanha_nome' as campanha_nome,
       e.occurred_at
  from public.lead_events e
 where e.event_type = 'entrada'
   and e.lead_id is not null
 order by e.lead_id, e.occurred_at asc, e.id asc;

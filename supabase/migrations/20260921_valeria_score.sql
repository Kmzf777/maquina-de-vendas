-- Deterministic ValerIA wholesale-score snapshots and seller-only Feelings.
-- The backend service role writes scores; authenticated sellers write only
-- their own feeling rows through the authenticated API route.

begin;

create or replace function public.valeria_score_set_score_updated_at()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'UPDATE' and old.source = 'live' and new.source = 'backfill' then
    return old;
  end if;
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.valeria_score_set_feeling_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.lead_qualification_scores (
  lead_id uuid primary key references public.leads(id) on delete cascade,
  segment text check (segment is null or segment in (
    'cafeteria', 'emporio', 'specialty_store', 'wine_shop', 'cheese_shop',
    'natural_products_store', 'bulk_store', 'artisan_store', 'colonial_store',
    'rural_store', 'supermarket', 'hotel', 'restaurant', 'bakery', 'other'
  )),
  monthly_volume_kg numeric check (monthly_volume_kg is null or monthly_volume_kg >= 0),
  supplier_reason text check (supplier_reason is null or supplier_reason in (
    'replace', 'second_supplier', 'expand_mix', 'start_specialty_coffee', 'research', 'other'
  )),
  purchase_timing text check (purchase_timing is null or purchase_timing in (
    'within_15_days', 'days_16_30', 'months_1_3', 'more_than_3_months', 'no_timeline'
  )),
  purchase_intent text check (purchase_intent is null or purchase_intent in ('clear', 'unclear')),
  evidence jsonb not null default '{}'::jsonb,
  normal_score smallint not null check (normal_score between 0 and 8),
  final_score smallint not null check (final_score in (0, 1, 2, 3, 4, 5, 6, 10)),
  priority text not null check (priority in ('low', 'moderate', 'high', 'maximum')),
  is_provisional boolean not null,
  source text not null check (source in ('live', 'backfill')),
  rule_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
  , constraint lead_qualification_scores_final_score_rule check (
    final_score = case
      when supplier_reason = 'replace' and purchase_intent = 'clear' then 10
      else normal_score
    end
  )
  , constraint lead_qualification_scores_normal_score_rule check (
    normal_score = (
      case segment
        when 'cafeteria' then 2
        when 'emporio' then 1
        when 'specialty_store' then 1
        when 'wine_shop' then 1
        when 'cheese_shop' then 1
        when 'natural_products_store' then 1
        when 'bulk_store' then 1
        when 'artisan_store' then 1
        when 'colonial_store' then 1
        when 'rural_store' then 1
        else 0
      end
      + case when monthly_volume_kg is not null and monthly_volume_kg <= 30 then 1 else 0 end
      + case when supplier_reason = 'replace' then 2 else 0 end
      + case when purchase_timing = 'within_15_days' then 1 else 0 end
      + case when purchase_intent = 'clear' then 2 else 0 end
    )
  )
  , constraint lead_qualification_scores_priority_rule check (
    priority = case
      when final_score = 10 then 'maximum'
      when final_score >= 5 then 'high'
      when final_score >= 3 then 'moderate'
      else 'low'
    end
  )
  , constraint lead_qualification_scores_provisional_rule check (
    is_provisional = (
      segment is null or monthly_volume_kg is null or supplier_reason is null
      or purchase_timing is null or purchase_intent is null
    )
  )
);

create index if not exists lead_qualification_scores_priority_score_idx
  on public.lead_qualification_scores (priority, final_score desc);

drop trigger if exists lead_qualification_scores_set_updated_at on public.lead_qualification_scores;
create trigger lead_qualification_scores_set_updated_at
  before update on public.lead_qualification_scores
  for each row execute function public.valeria_score_set_score_updated_at();

create table if not exists public.lead_seller_feelings (
  lead_id uuid not null references public.leads(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  seller_email text,
  feeling text not null check (feeling in ('baixo', 'medio', 'alto')),
  justification text not null check (length(btrim(justification)) > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (lead_id, user_id)
);

create index if not exists lead_seller_feelings_updated_at_idx
  on public.lead_seller_feelings (updated_at desc);

drop trigger if exists lead_seller_feelings_set_updated_at on public.lead_seller_feelings;
create trigger lead_seller_feelings_set_updated_at
  before update on public.lead_seller_feelings
  for each row execute function public.valeria_score_set_feeling_updated_at();

create or replace view public.valeria_score_directory
with (security_invoker = true) as
select
  l.id as lead_id,
  l.name,
  l.phone,
  l.company,
  l.stage,
  l.status,
  c.last_interaction_at,
  l.traffic_type,
  l.utm_campaign,
  l.meta_ad_id,
  coalesce(nullif(l.utm_campaign, ''), mac.campaign_name) as campaign_name,
  s.segment,
  s.monthly_volume_kg,
  s.supplier_reason,
  s.purchase_timing,
  s.purchase_intent,
  s.evidence,
  s.normal_score,
  s.final_score,
  s.priority,
  s.is_provisional,
  s.updated_at as score_updated_at
from public.leads l
left join public.lead_qualification_scores s on s.lead_id = l.id
left join public.meta_ad_campaigns mac on mac.ad_id = l.meta_ad_id
left join lateral (
  select max(conversations.last_msg_at) as last_interaction_at
  from public.conversations
  where conversations.lead_id = l.id
) c on true
where l.stage = 'atacado';

-- Collection/backfill eligibility is based on actual conversation activity,
-- not the legacy lead timestamp which can remain stale after new messages.
create or replace view public.valeria_score_recent_leads
with (security_invoker = true) as
select
  l.id as lead_id,
  max(c.last_msg_at) as last_interaction_at
from public.leads l
join public.conversations c on c.lead_id = l.id
where l.stage = 'atacado'
group by l.id;

alter table public.lead_qualification_scores enable row level security;
alter table public.lead_seller_feelings enable row level security;

drop policy if exists lead_seller_feelings_select_authenticated on public.lead_seller_feelings;
create policy lead_seller_feelings_select_authenticated
  on public.lead_seller_feelings for select to authenticated using (true);
drop policy if exists lead_seller_feelings_insert_own on public.lead_seller_feelings;
create policy lead_seller_feelings_insert_own
  on public.lead_seller_feelings for insert to authenticated
  with check (user_id = (select auth.uid()));
drop policy if exists lead_seller_feelings_update_own on public.lead_seller_feelings;
create policy lead_seller_feelings_update_own
  on public.lead_seller_feelings for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
drop policy if exists lead_seller_feelings_delete_own on public.lead_seller_feelings;
create policy lead_seller_feelings_delete_own
  on public.lead_seller_feelings for delete to authenticated
  using (user_id = (select auth.uid()));

commit;

notify pgrst, 'reload schema';

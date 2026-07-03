# Runbook — RLS Fase 3 em PRODUÇÃO (28 tabelas restantes)

> **Status:** homolog aplicado e validado em 03/07/2026 (0 de 28 tabelas sem RLS; smoke anon = 0 linhas em leads/token_usage/channels/tags). **Produção PENDENTE — requer autorização explícita do usuário** (regra do projeto para DDL em prod).

## O que aplica

Arquivo: `backend/migrations/20260703_rls_fase3_all_tables.sql` (defensivo/idempotente — statements guardados por `to_regclass`; o MESMO arquivo serve homolog e prod).

| Grupo | Tabelas | Policy |
|---|---|---|
| A (22) — zero acesso client-side | channels, agent_profiles, broadcast_leads, campaign_nodes, conversion_events, follow_up_jobs, lead_daily_sends, lead_events, lead_notes, lp_email_jobs, message_processing_locks, message_templates, messages_archive, meta_webhook_logs, model_pricing, old_messages, quick_replies, quick_send_phones, system_alerts, template_presets, templates, token_usage | RLS on, SEM policy (nega anon/authenticated; service_role passa) |
| B (5) — leitura client-side | tags, lead_tags | SELECT `authenticated USING (true)` (não segmentado; precedente sla_*/products) |
| | broadcasts, campaigns | SELECT admin OU dono do canal OU `channel_id IS NULL` (padrão Fase 2; NULL preserva telas atuais). Fecha o Realtime aberto (`broadcasts-changes`/`campaigns-realtime`) |
| | campaign_enrollments | SELECT via junção campaign→channels (mesma regra de NULL) |
| C (1) — write client-side | leads | SELECT/INSERT/UPDATE `authenticated` sem segmentação (fecha ANON — a vulnerabilidade real — preservando o CRM atual 1:1; DELETE segue só service-role) |

**Decisões registradas:** (1) `leads` NÃO segmentado por vendedor — leads não tem FK p/ channels; segmentar = decisão de produto futura (escopo transitivo via conversations + rework das telas /leads e /qualificacao). (2) `templates` tem zero referências no monorepo (possível legado) — confirmar com o time se pode ser dropada numa fase futura. (3) Realtime de broadcasts/campanhas/enrollments passa a ser ESCOPADO por vendedor — vendedor deixa de receber eventos de canais alheios (comportamento esperado, mesma mecânica da Fase 2).

## Como aplicar em PROD (MCP de prod é read-only)

Via Management API com o PAT do `.mcp.json` (mesmo caminho usado na Fase 2):

```
POST https://api.supabase.com/v1/projects/tshmvxxxyxgctrdkqvam/database/query
Authorization: Bearer <PAT do .mcp.json>
Content-Type: application/json
Body: {"query": "<conteúdo integral de 20260703_rls_fase3_all_tables.sql>"}
```

Pré-checks (já verificados em prod em 03/07, re-conferir se passar >1 semana): `broadcasts.channel_id`, `campaigns.channel_id`, `channels.owner_user_id` existem; `public.jwt_is_admin()` existe (Fase 2).

## Pós-checks

1. `SELECT count(*) FILTER (WHERE NOT relrowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace AND n.nspname='public' WHERE relkind='r';` → **0** (prod tem 38 tabelas; 10 já tinham RLS).
2. Advisors de segurança: `rls_disabled_in_public` deve zerar. WARNs ACEITOS (documentados): `rls_enabled_no_policy` INFO no Grupo A (intencional — negar é o objetivo); `rls_policy_always_true` nos INSERT/UPDATE de `leads` (decisão de preservação); `function_search_path_mutable` (pré-existente, follow-up de hardening separado — NÃO mexer em `jwt_is_admin` às pressas); leaked-password-protection (config de Auth, decisão do time).
3. Smoke anon (SQL editor): `BEGIN; SET LOCAL ROLE anon; SELECT (SELECT count(*) FROM leads), (SELECT count(*) FROM token_usage), (SELECT count(*) FROM channels); ROLLBACK;` → tudo **0**.
4. Smoke do CRM (com sessão de vendedor E de admin): kanban (deals), /leads e /qualificacao (leads+tags+lead_tags client-side), conversas (badge/preview), aba campanhas do lead (enrollments), página de disparos (broadcasts + realtime), quick-add lead (INSERT), "marcar perdido" no sidebar (UPDATE), som/toast de mensagem (Realtime já Fase 2).

## Rollback (por tabela, sem downtime)

`ALTER TABLE public.<tabela> DISABLE ROW LEVEL SECURITY;` (policies ficam inertes). Para reverter tudo da fase 3, repetir para as 28 tabelas do arquivo.

## Estado dos ambientes (03/07/2026)

- **Homolog (mosbwmsqfcwqdypucgtc):** fase 3 aplicada + drift pré-existente fechado (`pipelines/pipeline_stages/deals` — migração 20260618 nunca tinha sido aplicada lá; aplicada SEM o backfill de dados do João, que não se aplica a homolog). **0 tabelas sem RLS.**
- **Prod (tshmvxxxyxgctrdkqvam):** 10 tabelas com RLS (fases anteriores); 28 pendentes desta fase → este runbook.

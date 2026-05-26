# Spec: Banco de Homologação para o Rehearsal Runner

**Data:** 2026-05-26
**Branch:** feature/rehearsal-homologation-db

---

## Problema

O rehearsal runner (`scripts/outbound_rehearsal_runner.py`) usa o mesmo Supabase de produção. Durante migrações ou deploys, rodar o runner cria leads sintéticos no banco compartilhado, o que é arriscado. O objetivo é isolar completamente o rehearsal em um Supabase separado.

---

## Solução

Criar um projeto Supabase na nova conta (free tier), aplicar todas as migrations nele, semear os dados mínimos para o runner funcionar, e apontar `.env.local` para esse banco.

**Fluxo de migrations a partir de hoje:**

```
Escrever SQL
     ↓
Aplicar em HOMOLOGAÇÃO via MCP  ←── primeiro
     ↓
Rodar rehearsal runner → validar
     ↓
git push origin master → deploy → aplicar em PRODUÇÃO via MCP
```

Produção nunca recebe uma migration sem ter sido validada em homologação primeiro.

---

## Arquitetura

### O que muda

| Artefato | Mudança |
|----------|---------|
| `backend/migrations/rehearsal_seed.sql` | **Criar** — seed mínimo exclusivo de homologação |
| `backend/.env.local` | **Atualizar** — trocar credenciais Supabase para homologação |

**Nenhum código do backend é alterado.** Apenas configuração de ambiente e um arquivo de seed versionado.

### Por que o seed é necessário

O webhook router resolve o canal com:
```python
channel = get_channel_by_provider_config("phone_number_id", phone_number_id, "meta_cloud")
```
Se não houver canal com `provider_config->phone_number_id = "rehearsal"`, o router descarta o payload silenciosamente (`return {"status": "ok"}`). O processador nunca é chamado.

---

## Migrations a aplicar (em ordem)

### Grupo 1 — `backend/migrations/`

Aplicar todos os arquivos abaixo, nesta ordem, via MCP no projeto de homologação:

```
001_initial.sql
002_crm_enrichment.sql
003_cadence.sql
004_campaign_type.sql
005_token_usage.sql
006_lead_notes_events.sql
007_multi_channel.sql
008_agent_profile_seed.sql
009_deals.sql
009_multi_agent_schema.sql
010_campaigns_redesign.sql
011_message_templates.sql
012_multi_pipeline.sql
013_remove_funil_principal.sql
014_remove_test_pipelines.sql
20260417_conversations_ai_enabled.sql
20260417_fix_agent_profile_models.sql
20260418_broadcasts_template_language_code.sql
20260418_quick_send_phones.sql
20260424_last_customer_message_at.sql
20260427_get_last_messages_rpc.sql
20260429_backfill_ai_enabled_handoff.sql
20260429_conversations_unread_count.sql
20260430_ai_enabled_conversations_drop.sql
20260430_ai_enabled_leads_add.sql
20260430_messages_media_columns.sql
20260430_meta_webhook_logs.sql
20260501_normalize_phones_9th_digit.sql
20260514_broadcast_leads_claim.sql
20260514_broadcasts_env_tag.sql
20260514_seed_auth_users.sql
20260517_broadcast_atomic_counters_and_dedup_leads.sql
20260519_backfill_deal_moved_at.sql
20260519_broadcast_leads_deal_moved_at.sql
20260519_broadcast_leads_first_replied_at.sql
20260519_broadcast_reply_metrics_rpc.sql
20260519_templates_status_constraint.sql
20260522_backfill_sent_by.sql
20260522_get_last_messages_add_sent_by.sql
20260522_get_lead_deals_rpc.sql
20260523_handoff_rescue_job_type.sql
```

### Grupo 2 — `supabase/migrations/`

Aplicar após o Grupo 1:

```
20260521_automation_engine.sql
20260521_migrate_cadence_enrollments.sql
20260522_cadence_unify_drop_legacy.sql
20260523_templates_sync_unique_constraint.sql
20260524_add_notes_to_leads.sql
```

---

## Seed mínimo — `rehearsal_seed.sql`

O arquivo a criar em `backend/migrations/rehearsal_seed.sql`:

```sql
-- rehearsal_seed.sql
-- Seed EXCLUSIVO para o banco de homologação do rehearsal runner.
-- NÃO aplicar em produção.
--
-- Requisitos:
--   1. Canal com phone_number_id="rehearsal" para o webhook router encontrá-lo.
--   2. Agent profile valeria_outbound já criado por 009_multi_agent_schema.sql.

INSERT INTO channels (
    name,
    phone,
    provider,
    provider_config,
    agent_profile_id,
    is_active
)
VALUES (
    'Canal Rehearsal',
    'rehearsal',
    'meta_cloud',
    '{"phone_number_id": "rehearsal", "verify_token": "rehearsal", "access_token": "", "app_secret": ""}'::jsonb,
    (SELECT id FROM agent_profiles WHERE prompt_key = 'valeria_outbound' LIMIT 1),
    true
)
ON CONFLICT (phone) DO NOTHING;
```

**Notas:**
- O campo `phone` usa `"rehearsal"` como valor único — não é um número real, apenas um identificador de slot.
- `provider_config->phone_number_id = "rehearsal"` é o que o webhook router busca. O runner usa `META_PHONE_NUMBER_ID=rehearsal` por padrão.
- Com `REHEARSAL_MODE=true`, a verificação de assinatura HMAC é pulada (`meta_router.py:248-249`), então `app_secret` pode ficar vazio.
- O agent_profile `valeria_outbound` é criado por `009_multi_agent_schema.sql` — não precisa ser re-inserido aqui.

---

## Atualização do `.env.local`

Após aplicar todas as migrations e o seed, trocar as credenciais:

```bash
# === Supabase HOMOLOGAÇÃO (rehearsal) — ativo ===
SUPABASE_URL=https://<projeto-homologacao>.supabase.co
SUPABASE_SERVICE_KEY=<service-key-homologacao>
SUPABASE_JWT_SECRET=<jwt-secret-homologacao>

# === Supabase PRODUÇÃO — manter comentado; usar só no momento do deploy ===
# SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
# SUPABASE_SERVICE_KEY=<service-key-producao>
# SUPABASE_JWT_SECRET=<jwt-secret-producao>
```

`.env.local` está no `.dockerignore` e nunca chega à produção.

---

## Pré-requisito: MCP da nova conta

Antes de executar o plano, a nova conta Supabase precisa estar configurada no MCP do Claude Code. O plano inclui um passo explícito de pausa para isso.

---

## O que NÃO muda

- Código do backend (zero alterações)
- `.env` de produção (não tocar)
- Fluxo de deploy via GitHub Actions
- Redis (já era local em `.env.local`)

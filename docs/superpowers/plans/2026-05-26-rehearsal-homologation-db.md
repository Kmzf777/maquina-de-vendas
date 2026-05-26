# Rehearsal Homologation DB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolar o rehearsal runner em um Supabase de homologação separado, aplicando todas as migrations e o seed mínimo, e apontando `.env.local` para esse banco.

**Architecture:** Projeto Supabase separado (free tier, conta nova) recebe todas as ~46 migrations em ordem e o seed `rehearsal_seed.sql`. O arquivo `.env.local` passa a apontar para homologação; produção fica comentada. O código do backend não muda.

**Tech Stack:** Supabase MCP (Claude Code), SQL, `.env.local`

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `backend/migrations/rehearsal_seed.sql` | **Criar** — seed exclusivo de homologação |
| `backend/.env.local` | **Modificar** — trocar credenciais Supabase para homologação |

Nenhum outro arquivo é alterado.

---

### Task 1: Criar `rehearsal_seed.sql`

**Files:**
- Create: `backend/migrations/rehearsal_seed.sql`

- [ ] **Step 1: Criar o arquivo**

Criar `backend/migrations/rehearsal_seed.sql` com o seguinte conteúdo exato:

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

- [ ] **Step 2: Verificar o arquivo**

Confirmar que o arquivo foi criado em `backend/migrations/rehearsal_seed.sql` e que o conteúdo está correto.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/rehearsal_seed.sql
git commit -m "feat(migrations): adicionar rehearsal_seed.sql para homologação"
```

---

### Task 2: [BLOCKER] Configurar MCP da conta de homologação

**Esta task é um passo humano. Não prosseguir sem confirmação do usuário.**

- [ ] **Step 1: Solicitar ao usuário**

Perguntar ao usuário:
> "Para continuar, preciso que você adicione a nova conta Supabase ao MCP do Claude Code. Após configurar, me diga o nome do projeto de homologação para eu identificar o `project_id` correto."

- [ ] **Step 2: Listar projetos disponíveis no MCP**

Após confirmação, usar o Supabase MCP para listar os projetos disponíveis e identificar o `project_id` do projeto de homologação (não o de produção `tshmvxxxyxgctrdkqvam`).

- [ ] **Step 3: Confirmar projeto correto**

Confirmar com o usuário qual `project_id` é o de homologação antes de executar qualquer migration.

---

### Task 3: Aplicar Grupo 1 — `backend/migrations/`

**Pré-requisito:** Task 2 concluída. `project_id` da homologação identificado.

Para cada arquivo abaixo, na ordem listada: ler o conteúdo do arquivo e executar via Supabase MCP no projeto de homologação. Confirmar que cada execução não retorna erro antes de prosseguir para o próximo.

- [ ] **Step 1: Aplicar `001_initial.sql`**

  Ler `backend/migrations/001_initial.sql` e executar via MCP.

- [ ] **Step 2: Aplicar `002_crm_enrichment.sql`**

  Ler `backend/migrations/002_crm_enrichment.sql` e executar via MCP.

- [ ] **Step 3: Aplicar `003_cadence.sql`**

  Ler `backend/migrations/003_cadence.sql` e executar via MCP.

- [ ] **Step 4: Aplicar `004_campaign_type.sql`**

  Ler `backend/migrations/004_campaign_type.sql` e executar via MCP.

- [ ] **Step 5: Aplicar `005_token_usage.sql`**

  Ler `backend/migrations/005_token_usage.sql` e executar via MCP.

- [ ] **Step 6: Aplicar `006_lead_notes_events.sql`**

  Ler `backend/migrations/006_lead_notes_events.sql` e executar via MCP.

- [ ] **Step 7: Aplicar `007_multi_channel.sql`**

  Ler `backend/migrations/007_multi_channel.sql` e executar via MCP.
  
  > Cria as tabelas `agent_profiles` e `channels`. Tasks seguintes dependem delas.

- [ ] **Step 8: Aplicar `008_agent_profile_seed.sql`**

  Ler `backend/migrations/008_agent_profile_seed.sql` e executar via MCP.

- [ ] **Step 9: Aplicar `009_deals.sql`**

  Ler `backend/migrations/009_deals.sql` e executar via MCP.

- [ ] **Step 10: Aplicar `009_multi_agent_schema.sql`**

  Ler `backend/migrations/009_multi_agent_schema.sql` e executar via MCP.
  
  > Adiciona `prompt_key` em `agent_profiles` e insere o perfil `valeria_outbound`. O seed depende deste step.

- [ ] **Step 11: Aplicar `010_campaigns_redesign.sql`**

  Ler `backend/migrations/010_campaigns_redesign.sql` e executar via MCP.

- [ ] **Step 12: Aplicar `011_message_templates.sql`**

  Ler `backend/migrations/011_message_templates.sql` e executar via MCP.

- [ ] **Step 13: Aplicar `012_multi_pipeline.sql`**

  Ler `backend/migrations/012_multi_pipeline.sql` e executar via MCP.

- [ ] **Step 14: Aplicar `013_remove_funil_principal.sql`**

  Ler `backend/migrations/013_remove_funil_principal.sql` e executar via MCP.

- [ ] **Step 15: Aplicar `014_remove_test_pipelines.sql`**

  Ler `backend/migrations/014_remove_test_pipelines.sql` e executar via MCP.

- [ ] **Step 16: Aplicar `20260417_conversations_ai_enabled.sql`**

  Ler `backend/migrations/20260417_conversations_ai_enabled.sql` e executar via MCP.

- [ ] **Step 17: Aplicar `20260417_fix_agent_profile_models.sql`**

  Ler `backend/migrations/20260417_fix_agent_profile_models.sql` e executar via MCP.

- [ ] **Step 18: Aplicar `20260418_broadcasts_template_language_code.sql`**

  Ler `backend/migrations/20260418_broadcasts_template_language_code.sql` e executar via MCP.

- [ ] **Step 19: Aplicar `20260418_quick_send_phones.sql`**

  Ler `backend/migrations/20260418_quick_send_phones.sql` e executar via MCP.

- [ ] **Step 20: Aplicar `20260424_last_customer_message_at.sql`**

  Ler `backend/migrations/20260424_last_customer_message_at.sql` e executar via MCP.

- [ ] **Step 21: Aplicar `20260427_get_last_messages_rpc.sql`**

  Ler `backend/migrations/20260427_get_last_messages_rpc.sql` e executar via MCP.

- [ ] **Step 22: Aplicar `20260429_backfill_ai_enabled_handoff.sql`**

  Ler `backend/migrations/20260429_backfill_ai_enabled_handoff.sql` e executar via MCP.

- [ ] **Step 23: Aplicar `20260429_conversations_unread_count.sql`**

  Ler `backend/migrations/20260429_conversations_unread_count.sql` e executar via MCP.

- [ ] **Step 24: Aplicar `20260430_ai_enabled_conversations_drop.sql`**

  Ler `backend/migrations/20260430_ai_enabled_conversations_drop.sql` e executar via MCP.

- [ ] **Step 25: Aplicar `20260430_ai_enabled_leads_add.sql`**

  Ler `backend/migrations/20260430_ai_enabled_leads_add.sql` e executar via MCP.

- [ ] **Step 26: Aplicar `20260430_messages_media_columns.sql`**

  Ler `backend/migrations/20260430_messages_media_columns.sql` e executar via MCP.

- [ ] **Step 27: Aplicar `20260430_meta_webhook_logs.sql`**

  Ler `backend/migrations/20260430_meta_webhook_logs.sql` e executar via MCP.

- [ ] **Step 28: Aplicar `20260501_normalize_phones_9th_digit.sql`**

  Ler `backend/migrations/20260501_normalize_phones_9th_digit.sql` e executar via MCP.

- [ ] **Step 29: Aplicar `20260514_broadcast_leads_claim.sql`**

  Ler `backend/migrations/20260514_broadcast_leads_claim.sql` e executar via MCP.

- [ ] **Step 30: Aplicar `20260514_broadcasts_env_tag.sql`**

  Ler `backend/migrations/20260514_broadcasts_env_tag.sql` e executar via MCP.

- [ ] **Step 31: Aplicar `20260514_seed_auth_users.sql`**

  Ler `backend/migrations/20260514_seed_auth_users.sql` e executar via MCP.

- [ ] **Step 32: Aplicar `20260517_broadcast_atomic_counters_and_dedup_leads.sql`**

  Ler `backend/migrations/20260517_broadcast_atomic_counters_and_dedup_leads.sql` e executar via MCP.

- [ ] **Step 33: Aplicar `20260519_backfill_deal_moved_at.sql`**

  Ler `backend/migrations/20260519_backfill_deal_moved_at.sql` e executar via MCP.

- [ ] **Step 34: Aplicar `20260519_broadcast_leads_deal_moved_at.sql`**

  Ler `backend/migrations/20260519_broadcast_leads_deal_moved_at.sql` e executar via MCP.

- [ ] **Step 35: Aplicar `20260519_broadcast_leads_first_replied_at.sql`**

  Ler `backend/migrations/20260519_broadcast_leads_first_replied_at.sql` e executar via MCP.

- [ ] **Step 36: Aplicar `20260519_broadcast_reply_metrics_rpc.sql`**

  Ler `backend/migrations/20260519_broadcast_reply_metrics_rpc.sql` e executar via MCP.

- [ ] **Step 37: Aplicar `20260519_templates_status_constraint.sql`**

  Ler `backend/migrations/20260519_templates_status_constraint.sql` e executar via MCP.

- [ ] **Step 38: Aplicar `20260522_backfill_sent_by.sql`**

  Ler `backend/migrations/20260522_backfill_sent_by.sql` e executar via MCP.

- [ ] **Step 39: Aplicar `20260522_get_last_messages_add_sent_by.sql`**

  Ler `backend/migrations/20260522_get_last_messages_add_sent_by.sql` e executar via MCP.

- [ ] **Step 40: Aplicar `20260522_get_lead_deals_rpc.sql`**

  Ler `backend/migrations/20260522_get_lead_deals_rpc.sql` e executar via MCP.

- [ ] **Step 41: Aplicar `20260523_handoff_rescue_job_type.sql`**

  Ler `backend/migrations/20260523_handoff_rescue_job_type.sql` e executar via MCP.

- [ ] **Step 42: Verificar tabelas do Grupo 1**

  Executar via MCP:
  ```sql
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public'
  ORDER BY table_name;
  ```
  Confirmar que `agent_profiles`, `channels`, `leads`, `conversations`, `messages`, `campaigns`, `deals`, `broadcasts` estão presentes.

---

### Task 4: Aplicar Grupo 2 — `supabase/migrations/`

**Pré-requisito:** Task 3 concluída sem erros.

- [ ] **Step 1: Aplicar `20260521_automation_engine.sql`**

  Ler `supabase/migrations/20260521_automation_engine.sql` e executar via MCP.

- [ ] **Step 2: Aplicar `20260521_migrate_cadence_enrollments.sql`**

  Ler `supabase/migrations/20260521_migrate_cadence_enrollments.sql` e executar via MCP.

- [ ] **Step 3: Aplicar `20260522_cadence_unify_drop_legacy.sql`**

  Ler `supabase/migrations/20260522_cadence_unify_drop_legacy.sql` e executar via MCP.

- [ ] **Step 4: Aplicar `20260523_templates_sync_unique_constraint.sql`**

  Ler `supabase/migrations/20260523_templates_sync_unique_constraint.sql` e executar via MCP.

- [ ] **Step 5: Aplicar `20260524_add_notes_to_leads.sql`**

  Ler `supabase/migrations/20260524_add_notes_to_leads.sql` e executar via MCP.

- [ ] **Step 6: Verificar tabelas do Grupo 2**

  Executar via MCP:
  ```sql
  SELECT table_name FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name LIKE '%automation%'
     OR table_name LIKE '%cadence%'
  ORDER BY table_name;
  ```

---

### Task 5: Aplicar `rehearsal_seed.sql`

**Pré-requisito:** Tasks 3 e 4 concluídas. `agent_profiles` e `channels` existem no banco de homologação.

- [ ] **Step 1: Aplicar o seed**

  Ler `backend/migrations/rehearsal_seed.sql` e executar via MCP no projeto de homologação.

- [ ] **Step 2: Verificar inserção do canal**

  Executar via MCP:
  ```sql
  SELECT id, name, phone, provider,
         provider_config->>'phone_number_id' AS phone_number_id,
         is_active
  FROM channels
  WHERE phone = 'rehearsal';
  ```
  
  Resultado esperado: uma linha com `phone_number_id = 'rehearsal'` e `is_active = true`.

- [ ] **Step 3: Verificar agent_profile vinculado**

  Executar via MCP:
  ```sql
  SELECT c.name AS canal, ap.name AS agente, ap.prompt_key
  FROM channels c
  JOIN agent_profiles ap ON ap.id = c.agent_profile_id
  WHERE c.phone = 'rehearsal';
  ```
  
  Resultado esperado: `prompt_key = 'valeria_outbound'`.

---

### Task 6: Atualizar `backend/.env.local`

**Pré-requisito:** Task 5 concluída. Credenciais do projeto de homologação em mãos (obtidas no dashboard Supabase ou via MCP).

As credenciais necessárias são:
- `SUPABASE_URL` — URL do projeto de homologação (formato `https://<id>.supabase.co`)
- `SUPABASE_SERVICE_KEY` — service role key do projeto de homologação
- `SUPABASE_JWT_SECRET` — JWT secret do projeto de homologação (em Project Settings → API)

- [ ] **Step 1: Solicitar credenciais ao usuário**

  Se as credenciais não estiverem disponíveis via MCP, perguntar ao usuário:
  > "Preciso de três valores do projeto de homologação no Supabase dashboard (Project Settings → API): URL do projeto, service_role key e JWT secret."

- [ ] **Step 2: Atualizar `.env.local`**

  No arquivo `backend/.env.local`, substituir o bloco Supabase atual:

  ```
  # Supabase
  SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
  SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  SUPABASE_JWT_SECRET=super-secret-jwt-token-min-32-characters-long!
  ```

  Por:

  ```
  # === Supabase HOMOLOGAÇÃO (rehearsal) — ativo ===
  SUPABASE_URL=https://<projeto-homologacao>.supabase.co
  SUPABASE_SERVICE_KEY=<service-key-homologacao>
  SUPABASE_JWT_SECRET=<jwt-secret-homologacao>

  # === Supabase PRODUÇÃO — manter comentado; usar só no momento do deploy ===
  # SUPABASE_URL=https://tshmvxxxyxgctrdkqvam.supabase.co
  # SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRzaG12eHh4eXhnY3RyZGtxdmFtIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTUyNTIyNCwiZXhwIjoyMDkxMTAxMjI0fQ.Mav-FC0crAMByURUrqqwkG56VOpCDC5Nx8Hc3j2-WEk
  # SUPABASE_JWT_SECRET=super-secret-jwt-token-min-32-characters-long!
  ```

  Substituir os placeholders pelos valores reais do projeto de homologação.

- [ ] **Step 3: Habilitar REHEARSAL_MODE**

  Na mesma linha de `REHEARSAL_MODE` em `.env.local`, trocar de `false` para `true`:

  ```
  REHEARSAL_MODE=true
  ```

- [ ] **Step 4: Verificar que `.env.local` está no `.dockerignore`**

  Confirmar que `.env.local` está listado em `.dockerignore`. Se não estiver, adicionar. Este arquivo nunca deve chegar à produção.

  ```bash
  grep ".env.local" .dockerignore
  ```

  Esperado: linha com `.env.local` ou `*.local`.

- [ ] **Step 5: Commit**

  `.env.local` está no `.gitignore`? Verificar:

  ```bash
  git check-ignore -v backend/.env.local
  ```

  Se estiver ignorado (esperado), não commitá-lo. Apenas confirmar ao usuário que o arquivo foi atualizado.

---

### Task 7: Validar com o rehearsal runner

**Pré-requisito:** Tasks 5 e 6 concluídas. Backend local rodando com `.env.local` apontando para homologação.

- [ ] **Step 1: Iniciar o backend local**

  ```powershell
  cd backend
  $env:REHEARSAL_MODE = "true"
  ..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
  ```

  Aguardar `Application startup complete`.

- [ ] **Step 2: Rodar o rehearsal runner**

  Em outro terminal:

  ```powershell
  cd backend
  $env:REHEARSAL_MODE = "true"
  ..\.venv\Scripts\python -m scripts.outbound_rehearsal_runner
  ```

- [ ] **Step 3: Verificar resultado esperado**

  O runner deve:
  - Completar sem erros de conexão Supabase
  - Criar lead sintético no banco de **homologação** (não produção)
  - Exibir turnos de conversa no stdout

  Verificar no banco de homologação via MCP:
  ```sql
  SELECT phone, name, created_at FROM leads ORDER BY created_at DESC LIMIT 5;
  ```

  O número `REHEARSAL_PHONE` (`5534996652412`) deve aparecer.

- [ ] **Step 4: Confirmar isolamento — produção intacta**

  Verificar no banco de **produção** (via MCP, usando o project_id de produção `tshmvxxxyxgctrdkqvam`):
  ```sql
  SELECT COUNT(*) FROM leads WHERE phone = '5534996652412' AND created_at > NOW() - INTERVAL '1 hour';
  ```

  Resultado esperado: `0` — nenhum lead sintético criado em produção.

- [ ] **Step 5: Limpar leads de teste da homologação**

  ```powershell
  ..\.venv\Scripts\python -c "
  import asyncio
  from app.supabase_io import wipe_lead
  asyncio.run(wipe_lead('5534996652412'))
  "
  ```

- [ ] **Step 6: Confirmar ao usuário**

  Reportar: banco de homologação funcional, rehearsal runner isolado, produção não afetada.

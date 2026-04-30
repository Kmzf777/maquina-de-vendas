# Spec: Reativação da Valéria + Fixes de Disparo e Import

**Data:** 2026-04-30  
**Status:** Aprovado

---

## Contexto

A Valéria (inbound e outbound) está desativada por um kill switch global temporário. Antes de reativá-la, precisamos corrigir três bugs e adicionar logging de webhooks Meta.

---

## Problemas e Soluções

### 1. Kill switch global desligado
**Arquivo:** `backend/app/buffer/processor.py`  
**Bug:** `VALERIA_ENABLED = False` bloqueia 100% do processamento de AI.  
**Fix:** Setar `VALERIA_ENABLED = True`.

### 2. Broadcast sem agente não desativa AI na conversa
**Arquivo:** `backend/app/broadcast/worker.py`  
**Bug:** Ao criar/atualizar a conversa após envio de template, o worker não seta `ai_enabled`. Se o disparo não tem `agent_profile_id`, o lead que responde ainda é atendido pela Valéria.  
**Fix:** Sempre setar `ai_enabled` explicitamente no `conv_updates`:
- `agent_profile_id` presente → `ai_enabled = True`
- `agent_profile_id` ausente/null → `ai_enabled = False`

**Invariante:** disparo COM agente → AI entra ao responder; SEM agente → AI jamais entra.

### 3. Lead import sem normalização de telefone
**Arquivo:** `frontend/src/components/leads/lead-import-modal.tsx`  
**Bug:** O CSV é mapeado e enviado com os telefones no formato bruto (ex: `(34) 99999-9999`). A rota `/api/leads/import` não normaliza. Leads ficam com telefone inválido para o WhatsApp.  
**Fix:** Antes de enviar para `/api/leads/import`, normalizar cada `phone` usando a mesma lógica de `campaign/importer.normalize_phone`:
- Remove não-dígitos
- Remove leading `0`
- Adiciona `55` se 10 ou 11 dígitos
- Descarta phones inválidos (menos de 12 ou mais de 13 dígitos)
- Implementado em TypeScript puro no modal, sem dependência extra.

### 4. Meta webhook logs no Supabase
**Arquivo:** `backend/app/webhook/meta_router.py`  
**Requisito:** Todo payload recebido do Meta deve ser persistido no Supabase para auditoria e debugging.  
**Fix:**
- Criar migration `20260430_meta_webhook_logs.sql` com tabela `meta_webhook_logs`:
  - `id` UUID PK
  - `received_at` TIMESTAMPTZ
  - `channel_id` UUID nullable (pode não ter canal identificado)
  - `phone_number_id` TEXT nullable
  - `from_number` TEXT nullable
  - `payload` JSONB (payload completo)
  - `message_count` INT (quantas mensagens parseadas)
- Em `meta_router.py`, salvar como `background_task` após identificar o canal (fire-and-forget, nunca bloqueia o fluxo principal).

### 5. Processor: log quando AI é skipada
**Arquivo:** `backend/app/buffer/processor.py`  
**Melhoria:** Quando AI é pulada por `ai_enabled = False`, emitir log estruturado com `conversation_id`, `phone`, e motivo — facilita debugging futuro.  
**O log já existe parcialmente; torná-lo mais explícito.**

---

## Fluxo após fixes

```
Lead responde ao template
  └─ processor recebe mensagem
      ├─ se ai_enabled = False → log "AI disabled for conv X" → retorna (sem AI)
      └─ se ai_enabled = True e VALERIA_ENABLED = True → Valéria responde
```

```
Disparo criado:
  ├─ com agent_profile_id → conv: ai_enabled=True, agent_profile_id=X
  └─ sem agent_profile_id → conv: ai_enabled=False
```

---

## Arquivos afetados

| Arquivo | Tipo de mudança |
|---|---|
| `backend/app/buffer/processor.py` | Reativar kill switch + melhorar log |
| `backend/app/broadcast/worker.py` | Setar `ai_enabled` no `conv_updates` |
| `frontend/src/components/leads/lead-import-modal.tsx` | Normalizar telefone antes do import |
| `backend/app/webhook/meta_router.py` | Salvar payload em background task |
| `backend/migrations/20260430_meta_webhook_logs.sql` | Nova tabela `meta_webhook_logs` |

---

## O que está fora de escopo

- Refatoração do sistema de cadências
- Mudanças no UI de /campanhas
- Alterações no sistema de templates
- Mudanças no broadcast CSV import (já usa parse_csv com normalização)

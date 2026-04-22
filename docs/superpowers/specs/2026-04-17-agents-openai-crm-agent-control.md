# Spec: Migração dos Agentes para OpenAI + Controle de Agente no CRM

**Data:** 2026-04-17  
**Branch:** `feat/agents-openai-gpt4mini` (a partir de `feat/ux-redesign-v2`)  
**Status:** Aprovado para implementação

---

## Contexto

O backend atual usa o SDK OpenAI apontado para a **API Gemini** com `gemini-3-flash-preview` e `max_tokens=4096`. Isso causa comportamento completamente diferente do agente antigo (`agente-antigo/backend-evolution`), que usava GPT-4.1 com `max_tokens=500`. O agente inbound está "delirando" por causa dessa diferença de modelo + limite de tokens.

---

## Escopo

1. Migrar orchestrator para OpenAI real com `gpt-4.1-mini`
2. Corrigir prompts da Valeria Inbound (discrepâncias encontradas)
3. Reconstruir prompts da Valeria Outbound (agente antigo + bloco outbound)
4. Adicionar controle de agente no CRM (card de lista + sidebar de conversa)
5. Migração de banco de dados para suportar controle de agente por conversa

---

## 1. Orchestrator (`backend/app/agent/orchestrator.py`)

### Mudanças
- Remover `_GEMINI_BASE_URL` e toda referência à Gemini
- `_get_openai()` passa a usar `AsyncOpenAI(api_key=settings.openai_api_key)` sem `base_url`
- `DEFAULT_MODEL = "gpt-4.1-mini"` para ambos os agentes
- `max_tokens=500` em todas as chamadas (igual ao agente antigo)
- A resolução de perfil via `agent_profile_id` continua funcionando (o perfil no banco pode sobrescrever o modelo)

```python
# Antes
_openai_client = AsyncOpenAI(api_key=settings.gemini_api_key, base_url=_GEMINI_BASE_URL)
DEFAULT_MODEL = "gemini-3-flash-preview"
max_tokens=4096

# Depois
_openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
DEFAULT_MODEL = "gpt-4.1-mini"
max_tokens=500
```

---

## 2. Valeria Inbound — Correções

### `private_label.py` — ETAPA 4
- **Remover** referência direta ao vendedor pelo nome
- **Remover** link `wa.me/553493195252`
- **Substituir** por: `"um dos nossos vendedores vai dar continuidade aqui mesmo nesse chat"`
- A tool `encaminhar_humano` continua sendo chamada (sinaliza no CRM), mas o cliente não recebe nome/link

### `exportacao.py` — ETAPA 4
- Manter encaminhamento para Arthur (exportação é diferente — o Arthur gerencia de forma externa)
- Sem mudança de texto

### `tools.py` — schema `encaminhar_humano`
- Tornar `motivo` **opcional** no schema (remover de `required`, manter como property)
- O `execute_tool` já usa `args.get("vendedor", "Vendedor")`, mas `args['motivo']` pode quebrar — usar `args.get("motivo", "lead qualificado")`

---

## 3. Valeria Outbound — Reconstrução dos 5 stages

**Princípio:** Cada stage usa o prompt **completo do agente antigo** como corpo + bloco `CONTEXTO OUTBOUND` no topo. A Valéria outbound é **ativa**: apresenta, não aguarda.

### Bloco CONTEXTO OUTBOUND (padrão por stage)

```
## CONTEXTO OUTBOUND — ABORDAGEM ATIVA

Voce iniciou o contato com este lead. Leia o historico antes de qualquer coisa.

- Lead COM historico anterior: nao se apresente de novo. Retome pelo que foi dito.
- Lead SEM historico (primeiro contato): apresente a Cafe Canastra brevemente e crie interesse antes de qualificar.

POSTURA: voce nao espera o lead chegar com duvida ou interesse. Voce apresenta, cria curiosidade e conduz a conversa.
```

### `secretaria_outbound.py`
Bloco outbound + prompt completo da secretaria inbound.  
Adaptação no bloco: cenários específicos para lead novo (sem histórico) vs lead ocioso (com histórico).  
- Lead novo: apresenta Café Canastra brevemente antes de pedir o nome
- Lead ocioso: retoma pelo contexto anterior diretamente

### `atacado_outbound.py`
Bloco outbound + prompt completo atacado inbound.  
- ETAPA 0 contextual: se há histórico de produto/volume, referencia diretamente
- Mantém diagnóstico de dor completo, catálogo, frete, rapport

### `private_label_outbound.py`
Bloco outbound + prompt completo private_label inbound.  
- ETAPA 0: se já conversou sobre marca, retoma
- Remove link WhatsApp Joao Bras (mesmo comportamento inbound: vendedor continua no chat)

### `exportacao_outbound.py`
Bloco outbound + prompt completo exportacao inbound.  
- Encaminhamento para Arthur mantido (sem mudança)

### `consumo_outbound.py`
Bloco outbound + prompt completo consumo inbound.  
- ETAPA 0: se já enviou link/cupom antes, não envia de novo sem verificar

---

## 4. Controle de Agente no CRM

### 4a. Migração de banco (`conversations` table)

```sql
ALTER TABLE conversations
  ADD COLUMN agent_profile_id UUID REFERENCES agent_profiles(id) NULL,
  ADD COLUMN ai_enabled BOOLEAN NOT NULL DEFAULT TRUE;
```

- `ai_enabled = true` → agente IA responde normalmente
- `ai_enabled = false` → agente silenciado; vendedor humano assume
- `agent_profile_id = NULL` → usa o perfil padrão do canal (`channels.agent_profile_id`)
- `agent_profile_id = <id>` → sobrescreve o perfil do canal para esta conversa

### 4b. Backend — Buffer processor (`buffer/processor.py`)

O arquivo correto que controla o fluxo do agente é `buffer/processor.py`. Ele já:
- Lê `conversation.get("agent_profile_id")` para resolver o perfil
- Checa `lead.get("human_control")` para pular o agente

**Adições necessárias:** Após o check de `human_control`, adicionar check de `ai_enabled`:
```python
# Após check de human_control existente:
if not conversation.get("ai_enabled", True):
    logger.info(f"[AI DISABLED] Conversation {conversation['id']} — ai paused per CRM setting")
    _update_last_msg(conversation["id"])
    return
```

O `agent_profile_id` da conversa já tem prioridade sobre o do canal (lógica existente em `_resolve_agent_profile_id`).

**Nota:** `buffer/processor.py` também tem um cliente Gemini separado para transcrição de áudio e descrição de imagens (`_resolve_media`). Esse uso fica inalterado — é processamento de mídia, não o agente de venda.

### 4c. Backend — Novo endpoint

`PATCH /api/conversations/{id}/agent` com body:
```json
{
  "ai_enabled": true | false,
  "agent_profile_id": "<uuid>" | null
}
```

Retorna a conversation atualizada.

### 4d. Frontend — `Conversation` type

Adicionar ao tipo:
```typescript
agent_profile_id: string | null;
ai_enabled: boolean;
agent_profiles?: { id: string; name: string } | null;
```

### 4e. Frontend — Chat list card (`chat-list.tsx`)

No card de cada conversa, abaixo do nome/canal, adicionar indicador:
- Ponto verde pequeno + texto `"IA ativa"` quando `ai_enabled = true`
- Ponto cinza + texto `"IA pausada"` quando `ai_enabled = false`
- Aparece apenas se a conversa tem um agente configurado (canal com perfil ou conversa com perfil)

### 4f. Frontend — Contact detail sidebar (`contact-detail.tsx`)

Nova seção **"Agente IA"** no topo do painel (acima de "Stage (Agente)"):

```
─────────────────────────────────
AGENTE IA
Perfil: [Valeria Inbound ▾]     ← dropdown para trocar perfil
Status: ● Ativo  [Pausar]       ← toggle
─────────────────────────────────
```

- **Dropdown de perfil**: lista todos os `agent_profiles` disponíveis + opção "Padrão do canal"
- **Toggle ativo/pausado**: chama `PATCH /api/conversations/{id}/agent`
- Estado local otimista: atualiza UI imediatamente, reverte em caso de erro

---

## 5. Branch e Deploy

- Branch: `feat/agents-openai-gpt4mini` criada a partir de `feat/ux-redesign-v2`
- **Proibido push direto ao GitHub**
- Testes locais antes de qualquer merge
- A migração SQL deve rodar no Supabase antes dos testes de agente

---

## Arquivos afetados

**Backend:**
- `backend/app/agent/orchestrator.py`
- `backend/app/agent/tools.py`
- `backend/app/agent/prompts/valeria_inbound/private_label.py`
- `backend/app/agent/prompts/valeria_outbound/secretaria.py`
- `backend/app/agent/prompts/valeria_outbound/atacado.py`
- `backend/app/agent/prompts/valeria_outbound/private_label.py`
- `backend/app/agent/prompts/valeria_outbound/exportacao.py`
- `backend/app/agent/prompts/valeria_outbound/consumo.py`
- `backend/app/buffer/processor.py` (check `ai_enabled` antes de `run_agent`)
- `backend/app/conversations/service.py` (update_conversation com novos campos)
- Novo: `backend/app/conversations/router.py` — endpoint PATCH agent

**Frontend:**
- `frontend/src/lib/types.ts` — Conversation type
- `frontend/src/components/conversas/chat-list.tsx` — indicador IA no card
- `frontend/src/components/conversas/contact-detail.tsx` — seção Agente IA
- Novo: `frontend/src/app/api/conversations/[id]/agent/route.ts`

**Banco:**
- Migration: adicionar `agent_profile_id` e `ai_enabled` em `conversations`

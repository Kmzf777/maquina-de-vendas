# Design: Isolamento de IA por Canal — Novo Número WhatsApp (Phone ID 1079773125220705)

**Data:** 2026-05-19  
**Status:** Aprovado

---

## Contexto

A conta Meta da Canastra possui dois números WhatsApp sob o mesmo WABA (`1399531671927018`):

| Canal | Número | Phone ID | Função | mode |
|---|---|---|---|---|
| Canastra Meta Cloud | 553491461669 | 1049315514934778 | Vendedor humano | `human` ✅ |
| (novo) | a confirmar | 1079773125220705 | Atendimento IA | `ai` |

O canal do vendedor **nunca pode ter IA ativada**. O novo canal será exclusivo para a Valéria.

---

## Estado Atual do Banco (verificado via Supabase MCP em 2026-05-19)

- Coluna `mode` EXISTS em `channels` — `TEXT NOT NULL DEFAULT 'ai'`
- CHECK constraint `channels_mode_check` EXISTS — `CHECK (mode IN ('ai', 'human'))`
- Canal do vendedor já tem `mode = 'human'` — bloqueio já está ativo no banco
- Backend e frontend ainda **não expõem** o campo `mode` via API nem UI

---

## Arquitetura de Roteamento (sem mudanças necessárias)

O `meta_router.py` já roteia corretamente por `phone_number_id`:

```
Meta webhook POST /webhook/meta
  └── extract phone_number_id do payload
  └── get_channel_by_provider_config("phone_number_id", pid, "meta_cloud")
  └── cada canal resolve para uma linha distinta em `channels`
  └── msg.channel_id = channel["id"]  ← identidade imutável desde o primeiro byte
```

Dois Phone IDs diferentes sempre resolvem para dois canais diferentes. O WABA/token compartilhado é irrelevante para o roteamento.

---

## Gate de IA (três camadas, ordem de precedência)

```
processor.py — process_buffered_messages()

1. channel.mode == 'human'  →  return  (IA, follow-up, Valéria: bloqueados)
2. VALERIA_ENABLED == False →  return  (kill switch global)
3. lead.ai_enabled == False →  return  (controle por lead individual)
```

O mesmo guard em `mode == 'human'` existe em:
- `follow_up/scheduler.py:80` — cancela jobs de follow-up
- `follow_up/service.py:176` — exclui canais human do SELECT de jobs pendentes
- `broadcast/worker.py:207` — seta `ai_enabled=false` para leads de broadcasts

---

## Isolamento de Histórico

`conversations` tem `UNIQUE(lead_id, channel_id)`. Um lead que contata os dois números recebe duas linhas de conversa independentes. O agente usa `conversation_id` para buscar histórico — sem cruzamento.

---

## Gaps a Implementar

### 1. Backend — `channels/router.py`

Adicionar `mode` ao `ChannelCreate` e `ChannelUpdate`:

```python
class ChannelCreate(BaseModel):
    ...
    mode: str = "ai"  # "ai" | "human"

class ChannelUpdate(BaseModel):
    ...
    mode: str | None = None
```

Adicionar validação no endpoint POST:
```python
if body.mode not in ("ai", "human"):
    raise HTTPException(400, "mode must be 'ai' or 'human'")
```

### 2. Frontend — `/canais` page

**Formulário (Create/Edit):**
- Adicionar campo `mode: "ai" | "human"` ao `FormData` e `Channel` interface
- Adicionar toggle/select "Modo do Canal" entre `IA` e `Humano`
- Default: `"ai"` para novos canais
- Incluir `mode` no body do POST/PUT

**Tabela:**
- Adicionar coluna "Modo" com badge: `IA` (verde) | `Humano` (cinza)

### 3. Operacional — Cadastro do Novo Canal

Campos necessários para o novo canal via `/canais`:
- Nome: ex. `Canastra IA — Atendimento Automatizado`
- Telefone: número real associado ao Phone ID `1079773125220705` (a confirmar)
- Phone Number ID: `1079773125220705`
- Access Token: o mesmo system user token (ou token específico do número)
- App Secret: mesmo da conta Meta
- Verify Token: **deve ser único** — diferente do token do canal do vendedor
- WABA ID: `1399531671927018` (mesmo WABA)
- mode: `ai`
- Agente: perfil desejado (ex. Agente Canastra — Reciprocidade ou outro)

**No Meta Business Suite:** confirmar que o webhook `/webhook/meta` está subscrito ao novo Phone ID.

### 4. Testes de Validação (pré-produção)

```
[ ] Enviar msg para 553491461669 (vendedor) → zero resposta da IA nos logs do backend
[ ] Enviar msg para o novo número (IA)       → Valéria responde normalmente
[ ] Mesmo lead → ambos os números           → duas conversas separadas aparecem no CRM
[ ] Broadcast disparado pelo canal vendedor → ai_enabled=false setado no lead
[ ] Follow-up não agenda para canal vendedor → log [HUMAN CHANNEL] aparece
```

---

## O que NÃO muda

- Tabela `channels`: sem alterações de schema (banco já está correto)
- Lógica de roteamento em `meta_router.py`: sem alterações
- Lógica de gate em `processor.py`: sem alterações
- `leads.ai_enabled`: continua como controle por lead, ortogonal ao canal
- Dev Router: opera antes do parsing, independente do canal

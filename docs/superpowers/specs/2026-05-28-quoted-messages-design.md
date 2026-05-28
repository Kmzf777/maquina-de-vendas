# Quoted Messages (Citações) — Meta Cloud API

**Data:** 2026-05-28  
**Status:** Aprovado

---

## Visão Geral

Exibir o preview inline de mensagens citadas em `/conversas` quando um lead responde a uma mensagem anterior, e permitir que vendedores citem mensagens ao responder. Clicar no preview rola o chat até a mensagem original. Escopo limitado ao provider `meta_cloud`.

---

## Requisitos

### Recebimento (lead cita uma mensagem)
- Meta Cloud API envia `context.id` no payload do webhook quando a mensagem é uma reply
- O `context.id` é o `wamid` da mensagem original
- Armazenar `quoted_wamid` na mensagem recebida
- Resolver a mensagem citada via JOIN no banco (por `wamid`) ao retornar mensagens da conversa
- Exibir bloco de citação acima do conteúdo da mensagem

### Envio (vendedor cita uma mensagem)
- Interface: hover ou clique longo em qualquer mensagem exibe opção "Responder"
- Preview da mensagem selecionada aparece acima do input de texto com botão para cancelar
- Ao enviar, incluir `context: { message_id: wamid }` na chamada à Meta API
- Salvar `quoted_wamid` na mensagem enviada

### Display do bloco de citação
- **Texto**: exibir até 2 linhas truncadas do conteúdo
- **Mídia**: ícone + label do tipo (`📷 Imagem`, `🎵 Áudio`, `📄 Documento`, `🎬 Vídeo`, `😀 Figurinha`)
- **Mensagem não encontrada no banco**: exibir `"Mensagem original não disponível"`
- **Clique no bloco**: rolar chat suavemente até a mensagem original; piscar/highlight brevemente a mensagem

---

## Arquitetura

### Abordagem: Resolução server-side (JOIN na query)
O endpoint de mensagens faz JOIN entre `messages.quoted_wamid` e `messages.wamid` dentro da mesma conversa, retornando o objeto `quoted_message` inline. Nenhuma query extra no frontend.

---

## Banco de Dados

### Migration
```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS quoted_wamid TEXT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_wamid ON messages (wamid) WHERE wamid IS NOT NULL;
```

---

## Backend

### 1. `IncomingMessage` dataclass (`backend/app/webhook/parser.py`)
Adicionar campo: `quoted_wamid: str | None = None`

### 2. `meta_parser.py`
Extrair `context.id` do payload e populá-lo em `IncomingMessage.quoted_wamid`.

Payload Meta Cloud API (reply):
```json
{
  "type": "text",
  "text": { "body": "resposta do usuário" },
  "context": {
    "id": "wamid.yyy"
  }
}
```

### 3. `conversations/service.py` — `save_message()`
Persistir `quoted_wamid` ao salvar mensagem.

### 4. Endpoint de mensagens da conversa
Ao buscar mensagens, fazer self-JOIN:
```sql
SELECT m.*,
       q.id        AS q_id,
       q.content   AS q_content,
       q.role      AS q_role,
       q.message_type AS q_message_type,
       q.wamid     AS q_wamid
FROM messages m
LEFT JOIN messages q ON q.wamid = m.quoted_wamid
                     AND q.conversation_id = m.conversation_id
WHERE m.conversation_id = :conversation_id
ORDER BY m.created_at ASC;
```
Mapear resultado para incluir `quoted_message: { id, content, role, message_type }` ou `null`.

### 5. Envio de reply com citação (`meta_cloud` send message)
Localizar onde o backend envia mensagens via Meta API e adicionar suporte ao campo `context`:
```json
{
  "messaging_product": "whatsapp",
  "to": "phone",
  "type": "text",
  "context": { "message_id": "wamid.xxx" },
  "text": { "body": "resposta do vendedor" }
}
```

---

## Frontend

### 1. `types.ts`
```typescript
export interface QuotedMessage {
  id: string;
  content: string | null;
  role: string;
  message_type?: string | null;
}

// No interface Message:
quoted_wamid?: string | null;
quoted_message?: QuotedMessage | null;
```

### 2. `message-bubble.tsx`
Adicionar componente `QuotedBlock` acima do conteúdo principal:
- Barra colorida lateral (verde para mensagens do lead, cinza para as nossas)
- Ícone + tipo para mídia
- Texto truncado (2 linhas) para texto
- Placeholder se `quoted_message === null` e `quoted_wamid !== null`
- `onClick` dispara scroll para a mensagem original

### 3. `message-list.tsx`
- Criar `ref` map: `Map<messageId, HTMLElement>` para todas as mensagens renderizadas
- Expor função `scrollToMessage(id: string)` via `useImperativeHandle` ou contexto
- Ao scroll, destacar a mensagem por ~1.5s (ring/highlight animado com Tailwind)

### 4. `chat-view.tsx`
- Estado `replyingTo: Message | null`
- Hover em mensagem exibe botão "↩ Responder" (aparece no canto superior direito do bubble)
- Preview de citação acima do `<Textarea>` com botão `✕` para cancelar
- Ao submeter, incluir `quoted_wamid: replyingTo.wamid` no payload enviado ao backend
- Limpar `replyingTo` após envio

---

## Fluxo End-to-End

```
Lead cita mensagem no WhatsApp
  → Meta API webhook com context.id
  → meta_parser extrai quoted_wamid
  → save_message persiste quoted_wamid
  → GET /messages JOIN retorna quoted_message inline
  → message-bubble renderiza QuotedBlock
  → clique → scrollToMessage → highlight

Vendedor quer citar
  → hover → botão "Responder" → replyingTo state
  → preview acima do input
  → submit → POST com quoted_wamid
  → backend envia Meta API com context.message_id
  → mensagem salva com quoted_wamid
  → chat atualiza mostrando bloco de citação
```

---

## Fora do Escopo

- Provider Evolution API
- Citações aninhadas (cited dentro de cited)
- Reactions como citação
- Download/preview de mídia da mensagem citada (apenas ícone + tipo)

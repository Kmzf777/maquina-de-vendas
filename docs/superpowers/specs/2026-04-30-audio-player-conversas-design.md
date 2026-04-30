# Spec: Player de Áudio no /conversas (Meta Cloud API)

**Data:** 2026-04-30
**Branch:** feat/audio-player-conversas

---

## Problema

Leads enviam mensagens de áudio via WhatsApp (Meta Cloud API). No CRM em `/conversas`, esses áudios aparecem como texto (`[audio transcrito: ...]` ou `[audio: nao foi possivel transcrever]`) — sem nenhum player para ouvir. O vendedor precisa conseguir ouvir o áudio original.

---

## Solução

Adicionar um player de áudio nativo no `MessageBubble` para mensagens do tipo `audio`. O áudio é servido por uma rota proxy no Next.js que busca o conteúdo na Meta Graph API usando o `access_token` do canal — necessário porque a Meta exige autenticação para download de mídia.

---

## Arquitetura

```
Lead envia áudio (WhatsApp)
    → Meta webhook → meta_parser extrai media_id
    → buffer/processor salva message com media_url=<meta_media_id> e message_type="audio"
    → Frontend busca mensagens via /api/conversations/[id]/messages
    → MessageBubble detecta message_type="audio" → renderiza <audio>
    → <audio src="/api/media?media_id=XXX&conversation_id=YYY">
    → Proxy Next.js busca access_token do canal via conversation_id
    → Chama GET graph.facebook.com/{version}/{media_id} → retorna {url}
    → Faz download do áudio e stream para o browser
```

A transcrição via Whisper **continua acontecendo** para o agente IA processar o conteúdo. O `content` salvo no banco permanece com o texto transcrito (útil para busca/contexto do agente), mas o frontend **não exibe** o texto — mostra apenas o player.

---

## Mudanças necessárias

### 1. Migração SQL

Duas novas colunas na tabela `messages`:

```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_url TEXT;
```

`message_type`: `"audio"` | `"image"` | `"text"` | null (registros antigos = tratados como texto)
`media_url`: media ID da Meta para mensagens de mídia

### 2. Backend — `save_message()`

Adicionar parâmetros opcionais `media_url: str | None = None` e `message_type: str | None = None` ao `save_message()` em `conversations/service.py`. Quando presentes, incluir no payload do INSERT.

### 3. Backend — buffer/processor.py

No processamento de mensagens do buffer, identificar mensagens de tipo `audio` (via `IncomingMessage.type`) e passar `media_url` (o media ID da Meta) e `message_type="audio"` ao chamar `save_message()`.

O texto salvo em `content` continua sendo a transcrição (para o agente IA) — sem mudança na lógica de `_resolve_media`.

### 4. Next.js — Rota proxy `/api/media`

`GET /api/media?media_id=XXX&conversation_id=YYY`

Fluxo:
1. Validar `media_id` e `conversation_id`
2. Buscar `conversations` → `channels.provider_config` via Supabase (service role)
3. Extrair `access_token` e `api_version` do `provider_config`
4. `GET https://graph.facebook.com/{api_version}/{media_id}` com `Authorization: Bearer {token}` → retorna `{ url, mime_type }`
5. Fazer download do áudio a partir dessa URL (com mesmo Bearer token)
6. Fazer stream dos bytes para o browser com `Content-Type` correto

Segurança: a rota usa `getServiceSupabase()` (service role) e não expõe o `access_token` ao browser.

### 5. Frontend — `Message` type (`lib/types.ts`)

Adicionar campos opcionais:
```typescript
message_type?: string;
media_url?: string;
```

### 6. Frontend — `MessageBubble`

Quando `message.message_type === 'audio'` e `message.media_url`:
- Renderizar uma bolha com `<audio controls>` estilizado (estilo WhatsApp Web)
- `src` aponta para `/api/media?media_id={media_url}&conversation_id={conversationId}`
- Não mostrar `message.content` (transcrição fica oculta no frontend)
- Fallback: se sem `media_url`, mostrar ícone de microfone + texto "Áudio"

O `MessageBubble` precisa receber `conversationId` como prop adicional para montar a URL do proxy.

---

## Fora do escopo

- Imagens, vídeos e documentos (somente áudio nesta iteração)
- Mensagens de áudio antigas já salvas no banco (não têm `media_url` — exibem fallback)
- Waveform / visualização de forma de onda

---

## Critérios de aceite

1. Mensagem de áudio recebida via Meta aparece como player no CRM
2. Player toca o áudio sem erros
3. Mensagens de texto existentes não são afetadas
4. Mensagens de áudio antigas (sem `media_url`) exibem fallback gracioso
5. O `access_token` da Meta nunca é exposto ao browser

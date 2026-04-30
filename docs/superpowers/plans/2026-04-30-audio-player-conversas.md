# Audio Player no /conversas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exibir um player de áudio nativo no chat do CRM para mensagens de áudio recebidas via Meta Cloud API.

**Architecture:** O Meta media ID é armazenado junto com a mensagem no banco. Uma rota proxy Next.js (`/api/media`) busca o áudio na Meta Graph API usando o `access_token` do canal (nunca exposto ao browser) e faz streaming para o `<audio>` element. O `MessageBubble` detecta `message_type="audio"` e renderiza o player em vez de texto.

**Tech Stack:** Python/FastAPI (backend), Next.js App Router (frontend), Supabase (banco), Meta Graph API v21.0

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `backend/migrations/20260430_messages_media_columns.sql` | Criar | Adiciona `message_type` e `media_url` à tabela `messages` |
| `backend/app/conversations/service.py` | Modificar | `save_message()` aceita `media_url` e `message_type` opcionais |
| `backend/app/buffer/processor.py` | Modificar | Extrai `media_id` do `combined_text` e passa ao `save_message()` |
| `backend/tests/test_buffer.py` | Modificar | Testa extração de media_id do combined_text |
| `backend/tests/test_save_message_media.py` | Criar | Testa `save_message()` com os novos campos |
| `frontend/src/app/api/media/route.ts` | Criar | Proxy: busca áudio na Meta Graph API e faz streaming |
| `frontend/src/lib/types.ts` | Modificar | Adiciona `message_type?` e `media_url?` à interface `Message` |
| `frontend/src/components/conversas/message-bubble.tsx` | Modificar | Renderiza `<audio>` player quando `message_type === "audio"` |
| `frontend/src/components/conversas/message-list.tsx` | Modificar | Aceita e passa `conversationId` para `MessageBubble` |
| `frontend/src/components/conversas/chat-view.tsx` | Modificar | Passa `conversation.id` para `MessageList` |

---

## Task 1: Migração SQL — colunas `message_type` e `media_url`

**Files:**
- Create: `backend/migrations/20260430_messages_media_columns.sql`

- [ ] **Step 1: Criar o arquivo de migração**

```sql
-- backend/migrations/20260430_messages_media_columns.sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_url TEXT;
```

- [ ] **Step 2: Aplicar a migração no Supabase**

Use a ferramenta `mcp__supabase__apply_migration` com `name = "messages_media_columns"` e o SQL acima.

- [ ] **Step 3: Verificar que as colunas existem**

No Supabase SQL Editor (ou via MCP `execute_sql`):
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'messages'
  AND column_name IN ('message_type', 'media_url');
```
Expected: 2 linhas retornadas.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/20260430_messages_media_columns.sql
git commit -m "feat(db): add message_type and media_url columns to messages"
```

---

## Task 2: Backend — `save_message()` com campos de mídia

**Files:**
- Modify: `backend/app/conversations/service.py`
- Create: `backend/tests/test_save_message_media.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/test_save_message_media.py`:

```python
from unittest.mock import MagicMock, patch


def test_save_message_includes_media_fields():
    """save_message passes media_url and message_type to the DB insert."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message(
            "conv-id",
            "lead-id",
            "user",
            "[audio transcrito: oi tudo bem]",
            media_url="1234567890",
            message_type="audio",
        )

    insert_payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert insert_payload["media_url"] == "1234567890"
    assert insert_payload["message_type"] == "audio"


def test_save_message_without_media_fields():
    """save_message omits media keys when not provided (no None pollution)."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "abc-123"}
    ]
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message

        save_message("conv-id", "lead-id", "user", "olá")

    insert_payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert "media_url" not in insert_payload
    assert "message_type" not in insert_payload
```

- [ ] **Step 2: Rodar e verificar que falha**

```bash
cd /home/rafael/maquinadevendas/backend
python -m pytest tests/test_save_message_media.py -v
```
Expected: `TypeError: save_message() got an unexpected keyword argument 'media_url'`

- [ ] **Step 3: Modificar `save_message()` em `service.py`**

Localizar a função `save_message` em `backend/app/conversations/service.py` e alterar:

```python
def save_message(
    conversation_id: str,
    lead_id: str,
    role: str,
    content: str,
    stage: str | None = None,
    sent_by: str = "agent",
    media_url: str | None = None,
    message_type: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
        "sent_by": sent_by,
    }
    if media_url is not None:
        msg["media_url"] = media_url
    if message_type is not None:
        msg["message_type"] = message_type
    # ... resto da função sem alteração
```

- [ ] **Step 4: Rodar e verificar que passa**

```bash
cd /home/rafael/maquinadevendas/backend
python -m pytest tests/test_save_message_media.py -v
```
Expected: 2 testes PASS.

- [ ] **Step 5: Rodar a suite completa para garantir sem regressão**

```bash
cd /home/rafael/maquinadevendas/backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: todos os testes passam.

- [ ] **Step 6: Commit**

```bash
git add backend/app/conversations/service.py backend/tests/test_save_message_media.py
git commit -m "feat(backend): save_message accepts media_url and message_type"
```

---

## Task 3: Buffer Processor — extrair media_id e salvar com a mensagem

**Files:**
- Modify: `backend/app/buffer/processor.py`
- Modify: `backend/tests/test_buffer.py`

- [ ] **Step 1: Adicionar testes para extração de media_id**

Abrir `backend/tests/test_buffer.py` e adicionar ao final:

```python
import re as _re


def test_pure_audio_meta_media_id_extracted():
    """Pure audio combined_text yields a media_id match."""
    combined = "[audio: media_id=9876543210]"
    pattern = r"^\s*\[audio: media_id=(\S+)\]\s*$"
    m = _re.fullmatch(pattern, combined)
    assert m is not None
    assert m.group(1) == "9876543210"


def test_mixed_text_audio_not_pure_audio():
    """Text + audio buffer is NOT treated as pure audio (no media_id extracted)."""
    combined = "oi tudo bem\n[audio: media_id=9876543210]"
    pattern = r"^\s*\[audio: media_id=(\S+)\]\s*$"
    m = _re.fullmatch(pattern, combined)
    assert m is None
```

- [ ] **Step 2: Rodar para verificar que passam**

```bash
cd /home/rafael/maquinadevendas/backend
python -m pytest tests/test_buffer.py -v
```
Expected: todos passam (estes são testes puramente de regex, sem deps externas).

- [ ] **Step 3: Modificar `process_buffered_messages` no processor.py**

Localizar `process_buffered_messages` em `backend/app/buffer/processor.py`.

Após a linha `resolved_text = await _resolve_media(combined_text, provider)` (dentro do bloco try) e antes do bloco `save_message`, adicionar a extração do media_id:

```python
    # Extract media metadata for pure audio messages (Meta Cloud API)
    _audio_meta_pattern = r"^\s*\[audio: media_id=(\S+)\]\s*$"
    _audio_match = re.fullmatch(_audio_meta_pattern, combined_text)
    _media_url: str | None = _audio_match.group(1) if _audio_match else None
    _message_type: str | None = "audio" if _audio_match else None
```

Depois, na chamada `save_message` para a mensagem do usuário, adicionar os parâmetros:

```python
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
        )
```

> **Nota:** O módulo `re` já é importado no topo do arquivo (`import re`).

- [ ] **Step 4: Rodar a suite de testes do processor**

```bash
cd /home/rafael/maquinadevendas/backend
python -m pytest tests/test_processor_human_control.py tests/test_processor_errors.py tests/test_processor_delays.py -v --tb=short
```
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_buffer.py
git commit -m "feat(backend): store media_url and message_type for audio messages"
```

---

## Task 4: Next.js — Rota proxy `/api/media`

**Files:**
- Create: `frontend/src/app/api/media/route.ts`

- [ ] **Step 1: Criar a rota proxy**

Criar `frontend/src/app/api/media/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const mediaId = searchParams.get("media_id");
  const conversationId = searchParams.get("conversation_id");

  if (!mediaId || !conversationId) {
    return NextResponse.json({ error: "Missing media_id or conversation_id" }, { status: 400 });
  }

  const supabase = getServiceSupabase();
  const { data: conv } = await supabase
    .from("conversations")
    .select("channels(provider_config)")
    .eq("id", conversationId)
    .single();

  if (!conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  const config = (conv.channels as { provider_config: Record<string, string> } | null)
    ?.provider_config;
  const accessToken = config?.access_token;
  const apiVersion = config?.api_version ?? "v21.0";

  if (!accessToken) {
    return NextResponse.json({ error: "No access token configured" }, { status: 403 });
  }

  // Step 1: Resolve media_id → temporary download URL
  const infoRes = await fetch(
    `https://graph.facebook.com/${apiVersion}/${mediaId}`,
    { headers: { Authorization: `Bearer ${accessToken}` } }
  );
  if (!infoRes.ok) {
    return NextResponse.json({ error: "Meta media info fetch failed" }, { status: 502 });
  }
  const info = await infoRes.json() as { url?: string; mime_type?: string };
  const downloadUrl = info.url;
  const mimeType = info.mime_type ?? "audio/ogg";

  if (!downloadUrl) {
    return NextResponse.json({ error: "No download URL from Meta" }, { status: 502 });
  }

  // Step 2: Download audio bytes
  const audioRes = await fetch(downloadUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!audioRes.ok) {
    return NextResponse.json({ error: "Audio download failed" }, { status: 502 });
  }

  const audioBuffer = await audioRes.arrayBuffer();

  return new NextResponse(audioBuffer, {
    headers: {
      "Content-Type": mimeType,
      "Cache-Control": "private, max-age=3600",
    },
  });
}
```

- [ ] **Step 2: Verificar que o arquivo foi criado**

```bash
ls /home/rafael/maquinadevendas/frontend/src/app/api/media/route.ts
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/media/route.ts
git commit -m "feat(frontend): add /api/media proxy route for Meta audio"
```

---

## Task 5: Frontend — tipos e propagação do conversationId

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/components/conversas/message-list.tsx`
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Adicionar campos à interface `Message` em `types.ts`**

Abrir `frontend/src/lib/types.ts`. Localizar a interface `Message` e adicionar dois campos opcionais:

```typescript
export interface Message {
  id: string;
  lead_id: string;
  role: string;
  content: string;
  stage: string | null;
  sent_by: string;
  created_at: string;
  message_type?: string;
  media_url?: string;
}
```

- [ ] **Step 2: Adicionar `conversationId` ao `MessageListProps` em `message-list.tsx`**

Abrir `frontend/src/components/conversas/message-list.tsx`. Localizar `interface MessageListProps` e adicionar:

```typescript
interface MessageListProps {
  messages: Message[];
  loading: boolean;
  conversationId: string;
}
```

Atualizar a desestruturação na assinatura da função:

```typescript
export const MessageList = forwardRef<MessageListHandle, MessageListProps>(
  function MessageList({ messages, loading, conversationId }, ref) {
```

- [ ] **Step 3: Passar `conversationId` ao `MessageBubble` dentro do `MessageList`**

Ainda em `message-list.tsx`, localizar onde `MessageBubble` é renderizado (dentro do `.map`) e adicionar o prop:

```tsx
<MessageBubble
  key={msg.id}
  message={msg}
  isGrouped={isGrouped(msg, messages[idx - 1])}
  conversationId={conversationId}
/>
```

- [ ] **Step 4: Passar `conversation.id` ao `MessageList` em `chat-view.tsx`**

Abrir `frontend/src/components/conversas/chat-view.tsx`. Localizar o uso de `<MessageList` e adicionar `conversationId`:

```tsx
<MessageList
  key={conversation.id}
  messages={displayMessages}
  loading={loading}
  conversationId={conversation.id}
/>
```

- [ ] **Step 5: Verificar que não há erros de TypeScript**

```bash
cd /home/rafael/maquinadevendas/frontend
npx tsc --noEmit 2>&1 | head -40
```
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/types.ts \
        frontend/src/components/conversas/message-list.tsx \
        frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(frontend): propagate conversationId to MessageBubble for audio proxy"
```

---

## Task 6: Frontend — `MessageBubble` com player de áudio

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

- [ ] **Step 1: Adicionar `conversationId` ao `MessageBubbleProps` e renderizar o player**

Abrir `frontend/src/components/conversas/message-bubble.tsx` e substituir o conteúdo completo:

```tsx
import type { Message } from "@/lib/types";
import { formatTimeOnly } from "@/lib/datetime";

interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
  conversationId: string;
}

function getSenderBadge(message: Message): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  return null;
}

export function MessageBubble({ message, isGrouped, conversationId }: MessageBubbleProps) {
  const isFromMe = message.role === "assistant";
  const isTemp = message.id.startsWith("temp_");
  const senderBadge = getSenderBadge(message);

  const isAudio = message.message_type === "audio";

  return (
    <div
      className={`flex ${isFromMe ? "justify-end" : "justify-start"} ${isGrouped ? "mt-0.5" : "mt-2"}`}
    >
      <div
        className={`px-3 py-2 text-[14px] max-w-[75%] rounded-[8px] ${
          isFromMe
            ? "bg-[#111111] text-white ml-auto"
            : "bg-white border border-[#dedbd6] text-[#111111]"
        } ${isTemp ? "opacity-70" : ""}`}
      >
        {isAudio ? (
          message.media_url ? (
            <audio
              controls
              src={`/api/media?media_id=${message.media_url}&conversation_id=${conversationId}`}
              className="h-10 max-w-[240px]"
            />
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zm-1 3a1 1 0 0 1 2 0v8a1 1 0 0 1-2 0V4zm7.25 5a.75.75 0 0 0-1.5 0 5.75 5.75 0 0 1-11.5 0 .75.75 0 0 0-1.5 0 7.25 7.25 0 0 0 6.5 7.2V20H9a.75.75 0 0 0 0 1.5h6a.75.75 0 0 0 0-1.5h-2.25v-3.8A7.25 7.25 0 0 0 19.25 9z" />
              </svg>
              <span className="text-[13px] opacity-60">Áudio</span>
            </div>
          )
        ) : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
        <div className={`flex items-center gap-1 mt-1 ${isFromMe ? "justify-end" : "justify-start"}`}>
          <p
            className={`text-[11px] ${
              isFromMe ? "text-white/50" : "text-[#7b7b78]"
            }`}
          >
            {isTemp ? "Enviando..." : formatTimeOnly(message.created_at)}
          </p>
          {senderBadge && (
            <span
              className={`text-[10px] opacity-60 ${
                isFromMe ? "text-white" : "text-[#7b7b78]"
              }`}
            >
              · {senderBadge}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verificar TypeScript**

```bash
cd /home/rafael/maquinadevendas/frontend
npx tsc --noEmit 2>&1 | head -40
```
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(frontend): render audio player in MessageBubble for audio messages"
```

---

## Task 7: Verificação manual no dev

- [ ] **Step 1: Subir o ambiente de desenvolvimento**

Usar a VS Code task `Run All Dev (CRM & Backend)` ou:
```bash
# Terminal 1 — Backend
cd /home/rafael/maquinadevendas/backend && uvicorn app.main:app --reload

# Terminal 2 — Frontend
cd /home/rafael/maquinadevendas/frontend && npm run dev
```

- [ ] **Step 2: Testar com mensagem de áudio real**

1. Enviar um áudio via WhatsApp para o número da Canastra
2. Abrir o CRM em `/conversas`
3. Verificar que a mensagem aparece como player `<audio>` em vez de texto
4. Clicar em play — o áudio deve tocar

- [ ] **Step 3: Verificar regressão nas mensagens de texto**

Checar que mensagens de texto existentes continuam aparecendo normalmente (sem `message_type`, o `MessageBubble` cai no path de texto).

- [ ] **Step 4: Verificar mensagens antigas de áudio**

Mensagens já salvas com conteúdo `[audio transcrito: ...]` ou `[audio: nao foi possivel transcrever]` não têm `message_type="audio"` → aparecem como texto (comportamento anterior, aceitável).

- [ ] **Step 5: Commit final (se houver ajustes de polish)**

```bash
git add -p
git commit -m "fix(frontend): audio player polish adjustments"
```

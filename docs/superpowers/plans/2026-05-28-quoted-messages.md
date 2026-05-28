# Quoted Messages (Citações) — Meta Cloud API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Frontend tasks:** REQUIRED — invoke `frontend-design` skill before touching any frontend file. Use shadcn components.

**Goal:** Exibir preview inline de mensagens citadas em `/conversas` quando um lead responde via Meta Cloud API, e permitir que vendedores citem mensagens ao responder.

**Architecture:** Incoming Meta webhooks já chegam com `context.id` (wamid da mensagem citada). O `quoted_wamid` é propagado pelo buffer até `save_message`. No GET de mensagens, o API route resolve a mensagem citada por lookup no array já carregado (sem query extra). Na UI, o `MessageBubble` renderiza um bloco de citação acima do conteúdo; clicar rola o chat até a mensagem original via ref map no `MessageList`.

**Tech Stack:** Python/FastAPI (backend), Next.js App Router (frontend), Supabase (Postgres), Shadcn/ui + Tailwind CSS, Redis (buffer)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `supabase/migrations/20260528_quoted_messages.sql` | Create | Add `quoted_wamid` column + wamid index |
| `backend/app/webhook/parser.py` | Modify | Add `quoted_wamid` field to `IncomingMessage` |
| `backend/app/webhook/meta_parser.py` | Modify | Extract `context.id` → `quoted_wamid` |
| `backend/app/buffer/manager.py` | Modify | Store wamid/quoted_wamid in Redis, pass to processor |
| `backend/app/buffer/processor.py` | Modify | Accept + forward `wamid` and `quoted_wamid` to `save_message` |
| `backend/app/conversations/service.py` | Modify | Add `quoted_wamid` param to `save_message` |
| `frontend/src/app/api/conversations/[id]/messages/route.ts` | Modify | Resolve `quoted_message` via wamid lookup in fetched array |
| `frontend/src/app/api/conversations/[id]/send/route.ts` | Modify | Accept `quoted_wamid`, send `context` to Meta, save to DB |
| `frontend/src/lib/types.ts` | Modify | Add `QuotedMessage` interface + update `Message` |
| `frontend/src/components/conversas/message-bubble.tsx` | Modify | Add `QuotedBlock` sub-component + hover reply button |
| `frontend/src/components/conversas/message-list.tsx` | Modify | Add message ref map + `scrollToMessage` in handle |
| `frontend/src/components/conversas/chat-view.tsx` | Modify | Add `replyingTo` state, reply preview UI, pass `quoted_wamid` on send |
| `backend/tests/test_meta_quoted_messages.py` | Create | Tests for parser + buffer + save_message |
| `backend/tests/test_buffer_manager.py` | Modify | Update assertions for new `process_buffered_messages` signature |

---

## Task 1: DB Migration — `quoted_wamid` + wamid index

**Files:**
- Create: `supabase/migrations/20260528_quoted_messages.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/migrations/20260528_quoted_messages.sql

-- Column to store the wamid of the message being replied to
ALTER TABLE messages ADD COLUMN IF NOT EXISTS quoted_wamid TEXT NULL;

-- Index on wamid for fast lookup when resolving quoted messages
-- (wamid already exists as a column from previous migrations)
CREATE INDEX IF NOT EXISTS idx_messages_wamid
  ON messages (wamid)
  WHERE wamid IS NOT NULL;
```

- [ ] **Step 2: Apply via Supabase MCP**

Use `mcp__plugin_supabase_supabase__apply_migration` with the SQL above for the active project.

- [ ] **Step 3: Verify columns exist**

Run via MCP `execute_sql`:
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'messages'
  AND column_name IN ('wamid', 'quoted_wamid')
ORDER BY column_name;
```

Expected output: two rows — `quoted_wamid (text)` and `wamid (text)`.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/20260528_quoted_messages.sql
git commit -m "feat(db): add quoted_wamid column and wamid index to messages"
```

---

## Task 2: Backend — `IncomingMessage` + `meta_parser.py`

**Files:**
- Modify: `backend/app/webhook/parser.py`
- Modify: `backend/app/webhook/meta_parser.py`
- Create: `backend/tests/test_meta_quoted_messages.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_meta_quoted_messages.py
from app.webhook.meta_parser import parse_meta_webhook_payload
from app.webhook.parser import IncomingMessage


def _make_meta_payload(msg_dict: dict, from_number: str = "5511999999999") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5500000000000",
                        "phone_number_id": "999"
                    },
                    "contacts": [{"profile": {"name": "Test"}}],
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.reply1",
                        "timestamp": "1716900000",
                        **msg_dict,
                    }]
                }
            }]
        }]
    }


def test_parse_text_reply_with_context():
    """Text message quoting another message should populate quoted_wamid."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "sim, esse mesmo"},
        "context": {"id": "wamid.original1"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].text == "sim, esse mesmo"
    assert msgs[0].quoted_wamid == "wamid.original1"
    assert msgs[0].message_id == "wamid.reply1"


def test_parse_text_without_context():
    """Text message without context should have quoted_wamid = None."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "olá"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].quoted_wamid is None


def test_parse_image_reply_with_context():
    """Image message quoting another should populate quoted_wamid."""
    payload = _make_meta_payload({
        "type": "image",
        "image": {"id": "media123", "mime_type": "image/jpeg"},
        "context": {"id": "wamid.original2"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "image"
    assert msgs[0].quoted_wamid == "wamid.original2"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_meta_quoted_messages.py -v
```

Expected: FAIL — `IncomingMessage has no attribute 'quoted_wamid'` or `AssertionError`

- [ ] **Step 3: Add `quoted_wamid` to `IncomingMessage`**

In `backend/app/webhook/parser.py`, add the field after `metadata`:

```python
@dataclass
class IncomingMessage:
    from_number: str
    remote_jid: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, video, document
    text: str | None = None
    media_url: str | None = None
    media_mime: str | None = None
    push_name: str | None = None
    channel_id: str | None = None
    document_name: str | None = None
    metadata: dict | None = None
    quoted_wamid: str | None = None  # wamid of the message being replied to
```

- [ ] **Step 4: Extract `context.id` in `meta_parser.py`**

In `parse_meta_webhook_payload`, after the existing `msg_type` parsing block, before the `messages.append(...)` call at line 130, add extraction of `quoted_wamid`. Also update the `IncomingMessage(...)` call.

Replace the `messages.append(IncomingMessage(...))` block (lines 130–143) with:

```python
                quoted_wamid: str | None = msg.get("context", {}).get("id")

                messages.append(IncomingMessage(
                    from_number=from_number,
                    remote_jid="",
                    message_id=message_id,
                    timestamp=timestamp,
                    type=parsed_type,
                    text=text,
                    media_url=media_url,
                    media_mime=media_mime,
                    push_name=push_name,
                    document_name=document_name,
                    metadata=metadata_dict,
                    quoted_wamid=quoted_wamid,
                ))
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd backend && python -m pytest tests/test_meta_quoted_messages.py -v
```

Expected: 3 PASSED

- [ ] **Step 6: Run existing parser tests — no regression**

```bash
cd backend && python -m pytest tests/test_webhook_parser.py -v
```

Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/app/webhook/parser.py backend/app/webhook/meta_parser.py backend/tests/test_meta_quoted_messages.py
git commit -m "feat(webhook): add quoted_wamid to IncomingMessage and extract context.id from Meta payload"
```

---

## Task 3: Backend — Buffer flow (manager + processor)

**Files:**
- Modify: `backend/app/buffer/manager.py`
- Modify: `backend/app/buffer/processor.py`
- Modify: `backend/tests/test_buffer_manager.py`

The buffer combines multiple messages into one text, losing per-message metadata. Strategy: store `wamid` and `quoted_wamid` in Redis keys per phone+channel before buffering, then retrieve in processor. Last-write wins (acceptable — quotes are single-message replies).

- [ ] **Step 1: Write failing tests for new buffer signature**

Add to `backend/tests/test_buffer_manager.py`:

```python
async def test_push_imediato_passa_wamid_e_quoted_wamid(fake_redis):
    """Immediate mode deve passar wamid e quoted_wamid para process_buffered_messages."""
    await fake_redis.set("config:buffer_enabled", "0")
    msg = IncomingMessage(
        from_number="5511999999999",
        remote_jid="5511999999999@s.whatsapp.net",
        message_id="wamid.incoming1",
        timestamp="123",
        type="text",
        text="sim, esse mesmo",
        channel_id="chan-uuid",
        quoted_wamid="wamid.original1",
    )

    with patch("app.buffer.processor.process_buffered_messages", new_callable=AsyncMock) as mock_process:
        await push_to_buffer(fake_redis, msg)

    mock_process.assert_called_once_with(
        "5511999999999",
        "sim, esse mesmo",
        "chan-uuid",
        wamid="wamid.incoming1",
        quoted_wamid="wamid.original1",
    )
```

- [ ] **Step 2: Run test — expect fail**

```bash
cd backend && python -m pytest tests/test_buffer_manager.py::test_push_imediato_passa_wamid_e_quoted_wamid -v
```

Expected: FAIL

- [ ] **Step 3: Update `manager.py` to pass wamid and quoted_wamid**

In `push_to_buffer`, find the block where `buffer_enabled == "0"` and update the call:

```python
    if buffer_enabled == "0":
        logger.info(f"Buffer OFF — processing immediately for {phone}")
        await process_buffered_messages(
            phone, text, channel_id,
            wamid=msg.message_id or None,
            quoted_wamid=msg.quoted_wamid,
        )
        return
```

Still inside `push_to_buffer`, before the `await r.rpush(buf_key, text)` line, store meta in Redis (for buffered mode):

```python
    # Store per-message metadata for retrieval at flush time (last-write wins)
    if msg.message_id:
        await r.set(f"pending_wamid:{phone}:{channel_id}", msg.message_id, ex=120)
    if msg.quoted_wamid:
        await r.set(f"pending_quoted:{phone}:{channel_id}", msg.quoted_wamid, ex=120)
    elif msg.message_id:
        # No quoted_wamid — clear any stale value from previous messages
        await r.delete(f"pending_quoted:{phone}:{channel_id}")
```

In `_wait_and_flush`, retrieve and clear the stored metadata, then pass to processor:

```python
    if messages:
        combined = "\n".join(messages)
        pending_wamid = await r.get(f"pending_wamid:{phone}:{channel_id}")
        pending_quoted = await r.get(f"pending_quoted:{phone}:{channel_id}")
        await r.delete(f"pending_wamid:{phone}:{channel_id}")
        await r.delete(f"pending_quoted:{phone}:{channel_id}")
        logger.info(f"Buffer flushed for {phone}: {len(messages)} messages")
        await process_buffered_messages(
            phone, combined, channel_id,
            wamid=pending_wamid,
            quoted_wamid=pending_quoted,
        )
```

- [ ] **Step 4: Update `process_buffered_messages` signature in `processor.py`**

Find the function signature (line 133) and add the new params:

```python
async def process_buffered_messages(
    phone: str, combined_text: str, channel_id: str = "",
    wamid: str | None = None, quoted_wamid: str | None = None,
):
```

Then in the `save_message(...)` call for the user message (around line 176), add the new params:

```python
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
            document_name=_document_name,
            metadata=_metadata,
            wamid=wamid,
            quoted_wamid=quoted_wamid,
        )
```

- [ ] **Step 5: Fix the existing buffer test that checks the old signature**

In `test_buffer_manager.py`, find `test_push_texto_imediato_quando_buffer_desativado` and update its assertion:

```python
    mock_process.assert_called_once_with(
        "5511999999999", "oi direto", "chan-uuid",
        wamid=None, quoted_wamid=None,
    )
```

(The `_make_msg` helper uses `message_id="wamid.test1"` so `wamid` will be `"wamid.test1"`. Update accordingly:)

```python
    mock_process.assert_called_once_with(
        "5511999999999", "oi direto", "chan-uuid",
        wamid="wamid.test1", quoted_wamid=None,
    )
```

- [ ] **Step 6: Run all buffer tests**

```bash
cd backend && python -m pytest tests/test_buffer_manager.py -v
```

Expected: all PASSED

- [ ] **Step 7: Run full test suite**

```bash
cd backend && python -m pytest --tb=short -q
```

Expected: no new failures

- [ ] **Step 8: Commit**

```bash
git add backend/app/buffer/manager.py backend/app/buffer/processor.py backend/tests/test_buffer_manager.py
git commit -m "feat(buffer): propagate wamid and quoted_wamid through buffer to processor"
```

---

## Task 4: Backend — `save_message` accepts `quoted_wamid`

**Files:**
- Modify: `backend/app/conversations/service.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_meta_quoted_messages.py`:

```python
from unittest.mock import MagicMock, patch


def test_save_message_persists_quoted_wamid():
    """save_message deve incluir quoted_wamid no payload de insert quando fornecido."""
    captured = {}

    def fake_insert(data):
        captured["data"] = data
        mock_result = MagicMock()
        mock_result.data = [{**data, "id": "msg-uuid-1"}]
        return MagicMock(execute=MagicMock(return_value=mock_result))

    mock_table = MagicMock()
    mock_table.insert.side_effect = fake_insert

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_table

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message
        save_message(
            "conv-1", "lead-1", "user", "sim, esse mesmo",
            quoted_wamid="wamid.original1",
        )

    assert captured["data"].get("quoted_wamid") == "wamid.original1"


def test_save_message_omits_quoted_wamid_when_none():
    """save_message não deve incluir quoted_wamid no payload quando não fornecido."""
    captured = {}

    def fake_insert(data):
        captured["data"] = data
        mock_result = MagicMock()
        mock_result.data = [{**data, "id": "msg-uuid-2"}]
        return MagicMock(execute=MagicMock(return_value=mock_result))

    mock_table = MagicMock()
    mock_table.insert.side_effect = fake_insert
    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_table

    with patch("app.conversations.service.get_supabase", return_value=mock_sb):
        from app.conversations.service import save_message
        save_message("conv-1", "lead-1", "user", "olá")

    assert "quoted_wamid" not in captured["data"]
```

- [ ] **Step 2: Run tests — expect fail**

```bash
cd backend && python -m pytest tests/test_meta_quoted_messages.py::test_save_message_persists_quoted_wamid -v
```

Expected: FAIL — `save_message() got unexpected keyword argument 'quoted_wamid'`

- [ ] **Step 3: Update `save_message` in `service.py`**

Add `quoted_wamid: str | None = None` to the signature and persist it. The current signature ends at `metadata: dict | None = None`. Add after it:

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
    wamid: str | None = None,
    document_name: str | None = None,
    media_mime: str | None = None,
    metadata: dict | None = None,
    quoted_wamid: str | None = None,
) -> dict[str, Any]:
```

Then inside the function, after the `if metadata is not None:` block, add:

```python
    if quoted_wamid is not None:
        msg["quoted_wamid"] = quoted_wamid
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd backend && python -m pytest tests/test_meta_quoted_messages.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/conversations/service.py backend/tests/test_meta_quoted_messages.py
git commit -m "feat(service): save_message persists quoted_wamid"
```

---

## Task 5: Frontend API — messages GET resolves `quoted_message`

**Files:**
- Modify: `frontend/src/app/api/conversations/[id]/messages/route.ts`

The existing GET route fetches messages from Supabase. After fetching, build a `wamid → message` map and attach `quoted_message` inline. This approach avoids a self-JOIN and works within the Supabase JS client's capabilities.

- [ ] **Step 1: Locate the DB fetch block**

In the file, find the "Fallback: DB messages" comment block (around line 187):

```typescript
  // Fallback: DB messages — fetch latest 500 ordered descending, then reverse
  const { data, error } = await supabase
    .from("messages")
    .select("*")
    .eq("conversation_id", id)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json((data ?? []).reverse());
```

- [ ] **Step 2: Replace the return with quoted_message resolution**

```typescript
  // Fallback: DB messages — fetch latest 500 ordered descending, then reverse
  const { data, error } = await supabase
    .from("messages")
    .select("*")
    .eq("conversation_id", id)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const messages = (data ?? []).reverse();

  // Build wamid → message lookup for resolving quoted messages
  const wamidMap = new Map<string, typeof messages[0]>();
  for (const msg of messages) {
    if (msg.wamid) wamidMap.set(msg.wamid, msg);
  }

  // Attach quoted_message to each message that has quoted_wamid
  const enriched = messages.map((msg) => {
    if (!msg.quoted_wamid) return msg;
    const quoted = wamidMap.get(msg.quoted_wamid);
    return {
      ...msg,
      quoted_message: quoted
        ? {
            id: quoted.id,
            content: quoted.content,
            role: quoted.role,
            message_type: quoted.message_type ?? null,
          }
        : null,
    };
  });

  return NextResponse.json(enriched);
```

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/conversations/[id]/messages/route.ts"
git commit -m "feat(api): resolve quoted_message inline on messages GET"
```

---

## Task 6: Frontend API — send POST accepts `quoted_wamid`

**Files:**
- Modify: `frontend/src/app/api/conversations/[id]/send/route.ts`

- [ ] **Step 1: Update the POST handler to accept `quoted_wamid`**

Find the destructure line at the top of the POST function (line 18):

```typescript
  const { text } = await request.json();
```

Replace with:

```typescript
  const { text, quoted_wamid } = await request.json();
```

- [ ] **Step 2: Update `sendViaMeta` function to accept and use `context`**

Find the `sendViaMeta` function (around line 173) and update its signature and body:

```typescript
async function sendViaMeta(
  config: Record<string, string>,
  phone: string,
  text: string,
  quotedWamid?: string | null,
) {
  const phoneNumberId = config.phone_number_id || "";
  const accessToken = config.access_token || "";

  const body: Record<string, unknown> = {
    messaging_product: "whatsapp",
    to: phone,
    type: "text",
    text: { body: text },
  };

  if (quotedWamid) {
    body.context = { message_id: quotedWamid };
  }

  const res = await fetch(
    `https://graph.facebook.com/v21.0/${phoneNumberId}/messages`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    }
  );

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Meta API error: ${err}`);
  }

  const result = await res.json();
  // Return the wamid of the sent message if available
  return (result?.messages?.[0]?.id as string | undefined) ?? null;
}
```

- [ ] **Step 3: Update the call site for `sendViaMeta` and capture the wamid**

Find the `meta_cloud` branch (around line 111):

```typescript
    if (channel.provider === "evolution") {
      await sendViaEvolution(channel.provider_config, lead.phone, text.trim());
    } else if (channel.provider === "meta_cloud") {
      await sendViaMeta(channel.provider_config, lead.phone, text.trim());
    }
```

Replace with:

```typescript
    let sentWamid: string | null = null;
    if (channel.provider === "evolution") {
      await sendViaEvolution(channel.provider_config, lead.phone, text.trim());
    } else if (channel.provider === "meta_cloud") {
      sentWamid = await sendViaMeta(
        channel.provider_config,
        lead.phone,
        text.trim(),
        quoted_wamid ?? null,
      );
    } else {
      return NextResponse.json({ error: "Unknown provider" }, { status: 400 });
    }
```

- [ ] **Step 4: Include `quoted_wamid` and `wamid` in the DB insert**

Find the DB insert block (around line 118):

```typescript
    // Save message to DB
    await supabase.from("messages").insert({
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: text.trim(),
      sent_by: "seller",
      stage: conv.stage || "secretaria",
    });
```

Replace with:

```typescript
    // Save message to DB
    const insertData: Record<string, unknown> = {
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: text.trim(),
      sent_by: "seller",
      stage: conv.stage || "secretaria",
    };
    if (sentWamid) {
      insertData.wamid = sentWamid;
      insertData.delivery_status = "sent";
    }
    if (quoted_wamid) {
      insertData.quoted_wamid = quoted_wamid;
    }
    await supabase.from("messages").insert(insertData);
```

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/app/api/conversations/[id]/send/route.ts"
git commit -m "feat(api): send route accepts quoted_wamid and forwards context to Meta API"
```

---

## Task 7: Frontend — `types.ts`

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Add `QuotedMessage` interface and update `Message`**

After the `export interface Message {` closing brace (line 92), add:

```typescript
export interface QuotedMessage {
  id: string;
  content: string | null;
  role: string;
  message_type?: string | null;
}
```

Then in the `Message` interface, add two fields after `delivery_status`:

```typescript
  quoted_wamid?: string | null;
  quoted_message?: QuotedMessage | null;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(types): add QuotedMessage interface and quoted fields to Message"
```

---

## Task 8: Frontend — `message-bubble.tsx` (QuotedBlock + reply button)

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

> **REQUIRED:** Invoke `frontend-design` skill before implementing.

- [ ] **Step 1: Invoke `frontend-design` skill**

Use the Skill tool with `frontend-design:frontend-design` before writing any code.

- [ ] **Step 2: Add `QuotedBlock` component and update props**

At the top of the file, add the import for `QuotedMessage` type. Then add the `QuotedBlock` component before `MessageBubble`:

```typescript
import type { Message, QuotedMessage } from "@/lib/types";

function getMediaIcon(messageType: string | null | undefined): string {
  switch (messageType) {
    case "image": return "📷 Imagem";
    case "audio": return "🎵 Áudio";
    case "video": return "🎬 Vídeo";
    case "document": return "📄 Documento";
    case "sticker": return "😀 Figurinha";
    case "location": return "📍 Localização";
    case "contact": return "👤 Contato";
    default: return "📎 Mídia";
  }
}

function QuotedBlock({
  quoted,
  isFromMe,
  onClick,
}: {
  quoted: QuotedMessage | null;
  isFromMe: boolean;
  onClick: () => void;
}) {
  const barColor = isFromMe ? "bg-white/40" : "bg-[#25d366]";
  const isText = !quoted?.message_type || quoted.message_type === "text";

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-md mb-1 overflow-hidden flex ${
        isFromMe
          ? "bg-white/20 hover:bg-white/30"
          : "bg-black/5 hover:bg-black/10"
      } transition-colors`}
    >
      <div className={`w-1 flex-shrink-0 ${barColor}`} />
      <div className="px-2 py-1.5 min-w-0 flex-1">
        {!quoted ? (
          <p className="text-xs opacity-60 italic">Mensagem original não disponível</p>
        ) : (
          <>
            <p className="text-xs font-medium opacity-70 mb-0.5">
              {quoted.role === "user" ? "Lead" : "Você"}
            </p>
            <p className="text-xs opacity-60 truncate">
              {isText
                ? (quoted.content ?? "")
                : getMediaIcon(quoted.message_type)}
            </p>
          </>
        )}
      </div>
    </button>
  );
}
```

- [ ] **Step 3: Update `MessageBubbleProps` and render `QuotedBlock`**

Update the props interface:

```typescript
interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
  conversationId: string;
  onReply?: (msg: Message) => void;
  onScrollToMessage?: (messageId: string) => void;
}
```

Update the function signature:

```typescript
export function MessageBubble({ message, isGrouped, conversationId, onReply, onScrollToMessage }: MessageBubbleProps) {
```

Inside the bubble content area (right before the text/media content rendering), add the `QuotedBlock`. Find the JSX section where bubble content is rendered. After the sender badge and before the main content, insert:

```tsx
{/* Quoted message block */}
{(message.quoted_message !== undefined || message.quoted_wamid) && (
  <QuotedBlock
    quoted={message.quoted_message ?? null}
    isFromMe={isFromMe}
    onClick={() => {
      if (message.quoted_message?.id) {
        onScrollToMessage?.(message.quoted_message.id);
      }
    }}
  />
)}
```

- [ ] **Step 4: Add hover reply button**

Wrap the outer bubble `<div>` in a `group` class and add the reply button. Find the outermost flex container of the bubble and add:

```tsx
{/* Reply button — appears on hover */}
{onReply && !isTemp && (
  <button
    onClick={() => onReply(message)}
    className={`absolute top-1 opacity-0 group-hover:opacity-100 transition-opacity z-10 p-1.5 rounded-full bg-[#f0f0f0] hover:bg-[#e0e0e0] shadow-sm text-[#555] ${
      isFromMe ? "-left-8" : "-right-8"
    }`}
    title="Responder"
    aria-label="Responder"
  >
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 17 4 12 9 7" />
      <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
    </svg>
  </button>
)}
```

Add `group relative` to the outermost `<div>` of the message row (the one that sets flex direction based on `isFromMe`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(ui): add QuotedBlock and reply button to MessageBubble"
```

---

## Task 9: Frontend — `message-list.tsx` (scroll to message + ref map)

**Files:**
- Modify: `frontend/src/components/conversas/message-list.tsx`

> **REQUIRED:** Invoke `frontend-design` skill before implementing.

- [ ] **Step 1: Invoke `frontend-design` skill**

Use the Skill tool with `frontend-design:frontend-design` before writing any code.

- [ ] **Step 2: Extend `MessageListHandle` and add props**

Update the handle interface and add new props:

```typescript
export interface MessageListHandle {
  scrollToBottom: () => void;
  scrollToMessage: (messageId: string) => void;
}

interface MessageListProps {
  messages: Message[];
  loading: boolean;
  conversationId: string;
  onReply?: (msg: Message) => void;
}
```

- [ ] **Step 3: Add ref map and highlight state**

Inside the component, add after existing refs:

```typescript
const messageRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());
const [highlightedId, setHighlightedId] = useState<string | null>(null);
```

- [ ] **Step 4: Extend `useImperativeHandle`**

```typescript
useImperativeHandle(ref, () => ({
  scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  },
  scrollToMessage(id: string) {
    const el = messageRefsMap.current.get(id);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedId(id);
    setTimeout(() => setHighlightedId(null), 1500);
  },
}));
```

- [ ] **Step 5: Attach refs to message rows and pass props down**

Update the `messages.map` render to attach refs and pass `onReply` and `onScrollToMessage`:

```tsx
{messages.map((msg, idx) => {
  const prev = messages[idx - 1];
  const currDate = new Date(msg.created_at);
  const prevDate = prev ? new Date(prev.created_at) : null;
  const showDaySep = !prevDate || !isSameDay(currDate, prevDate);
  const grouped = isGrouped(msg, prev);
  const isHighlighted = highlightedId === msg.id;

  return (
    <div
      key={msg.id}
      ref={(el) => {
        if (el) messageRefsMap.current.set(msg.id, el);
        else messageRefsMap.current.delete(msg.id);
      }}
      className={`transition-colors duration-300 rounded-lg ${
        isHighlighted ? "bg-yellow-100/60" : ""
      }`}
    >
      {showDaySep && <DaySeparator date={currDate} />}
      {msg.role === "system" ? (
        <EventCard message={msg} />
      ) : (
        <MessageBubble
          message={msg}
          isGrouped={grouped}
          conversationId={conversationId}
          onReply={onReply}
          onScrollToMessage={(targetId) => {
            const el = messageRefsMap.current.get(targetId);
            if (!el) return;
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            setHighlightedId(targetId);
            setTimeout(() => setHighlightedId(null), 1500);
          }}
        />
      )}
    </div>
  );
})}
```

- [ ] **Step 6: Update the function signature**

```typescript
export const MessageList = forwardRef<MessageListHandle, MessageListProps>(
  function MessageList({ messages, loading, conversationId, onReply }, ref) {
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/conversas/message-list.tsx
git commit -m "feat(ui): add scrollToMessage and message ref map to MessageList"
```

---

## Task 10: Frontend — `chat-view.tsx` (reply UI + pass quoted_wamid to send)

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

> **REQUIRED:** Invoke `frontend-design` skill before implementing.

- [ ] **Step 1: Invoke `frontend-design` skill**

Use the Skill tool with `frontend-design:frontend-design` before writing any code.

- [ ] **Step 2: Add `replyingTo` state**

After the existing state declarations (around line 36), add:

```typescript
const [replyingTo, setReplyingTo] = useState<Message | null>(null);
const messageListRef = useRef<MessageListHandle>(null);
```

Note: `MessageListHandle` must be imported. Add to imports:

```typescript
import { MessageList, type MessageListHandle } from "@/components/conversas/message-list";
```

- [ ] **Step 3: Clear `replyingTo` on conversation change**

Inside the `useEffect(() => { ... }, [conversation.id])` cleanup block, add:

```typescript
setReplyingTo(null);
```

- [ ] **Step 4: Update `handleSend` to include `quoted_wamid`**

Update `tempMsg` to include the quoted message for optimistic UI:

```typescript
const tempMsg: Message = {
  id: `temp_${Date.now()}`,
  lead_id: lead?.id ?? "",
  role: "assistant",
  content,
  stage: null,
  sent_by: "seller",
  created_at: new Date().toISOString(),
  quoted_wamid: replyingTo?.wamid ?? undefined,
  quoted_message: replyingTo
    ? {
        id: replyingTo.id,
        content: replyingTo.content,
        role: replyingTo.role,
        message_type: replyingTo.message_type ?? null,
      }
    : undefined,
};
```

Update the `body` sent to the API:

```typescript
body: JSON.stringify({
  text: content,
  ...(replyingTo?.wamid ? { quoted_wamid: replyingTo.wamid } : {}),
}),
```

Clear `replyingTo` after sending (in the `finally` block, before `sendingRef.current = false`):

```typescript
setReplyingTo(null);
```

- [ ] **Step 5: Add reply preview bar above textarea**

Locate the textarea/input area in the JSX render. Add the reply preview above it:

```tsx
{/* Reply preview */}
{replyingTo && (
  <div className="mx-3 mb-1 flex items-center gap-2 rounded-lg border-l-4 border-[#25d366] bg-[#f7f7f7] pl-2 pr-3 py-2">
    <div className="flex-1 min-w-0">
      <p className="text-xs font-medium text-[#25d366] mb-0.5">
        {replyingTo.role === "user" ? "Lead" : "Você"}
      </p>
      <p className="text-xs text-[#666] truncate">
        {replyingTo.message_type && replyingTo.message_type !== "text"
          ? {
              image: "📷 Imagem",
              audio: "🎵 Áudio",
              video: "🎬 Vídeo",
              document: "📄 Documento",
              sticker: "😀 Figurinha",
            }[replyingTo.message_type] ?? "📎 Mídia"
          : replyingTo.content}
      </p>
    </div>
    <button
      onClick={() => setReplyingTo(null)}
      className="text-[#999] hover:text-[#333] transition-colors flex-shrink-0"
      aria-label="Cancelar resposta"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    </button>
  </div>
)}
```

- [ ] **Step 6: Pass `onReply` to `MessageList` and add ref**

Find the `<MessageList ... />` usage in the JSX and update it:

```tsx
<MessageList
  ref={messageListRef}
  messages={displayMessages}
  loading={loading}
  conversationId={conversation.id}
  onReply={(msg) => setReplyingTo(msg)}
/>
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(ui): add reply UI, replyingTo state and quoted_wamid to chat-view"
```

---

## Self-Review Checklist

**Spec coverage check:**
- [x] Recebimento: meta_parser extrai context.id → Tasks 2, 3, 4
- [x] Envio com citação: send route aceita quoted_wamid e passa context → Task 6
- [x] Display: QuotedBlock em message-bubble → Task 8
- [x] Scroll ao clicar: ref map + scrollToMessage → Task 9
- [x] Reply UI no painel: replyingTo state + preview → Task 10
- [x] Placeholder "não disponível": QuotedBlock com `quoted === null` → Task 8
- [x] DB migration: quoted_wamid column + wamid index → Task 1
- [x] Tipos TypeScript: QuotedMessage + Message update → Task 7
- [x] Resolução server-side: messages GET enriquece quoted_message → Task 5

**Type consistency:**
- `QuotedMessage` interface definida em Task 7, usada em Tasks 8, 9, 10 ✓
- `MessageListHandle.scrollToMessage(id: string)` definido em Task 9, consumido em Task 10 ✓
- `MessageBubbleProps.onReply` e `onScrollToMessage` definidos em Task 8, passados em Task 9 ✓
- `quoted_wamid` no body do POST: Task 6 lê, Task 10 envia ✓

**No placeholders:** Todos os steps têm código concreto ✓

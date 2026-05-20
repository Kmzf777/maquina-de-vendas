# Plano: Suporte Completo a Tipos de Mensagem WhatsApp em /conversas

> **Para agentes:** Use `superpowers:subagent-driven-development` ou `superpowers:executing-plans`.  
> **FRONTEND OBRIGATÓRIO:** Todo agente que tocar arquivos frontend DEVE invocar a skill `frontend-design` antes de implementar.  
> **ESCOPO:** Meta Cloud API apenas. Não altere parser.py (Evolution) além dos campos opcionais no dataclass.

**Goal:** Fazer com que todos os tipos de mensagem WhatsApp (documento, sticker, localização, contato, reação) sejam recebidos, salvos e exibidos corretamente em /conversas.

**Branch:** `feat/conversas-media-display`

---

## Ação Manual Prévia (Usuário Executa no Supabase)

Antes de qualquer código, o usuário precisa rodar esta migration no Supabase Dashboard → SQL Editor:

```sql
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS document_name TEXT,
  ADD COLUMN IF NOT EXISTS media_mime    TEXT,
  ADD COLUMN IF NOT EXISTS metadata      JSONB;
```

---

## Estrutura de Paralelismo

```
Round 1 (paralelo):
  Agente Backend-A: Task 1 → Task 2 → Task 3 (sequencial dentro do agente)
  Agente Frontend-A: Task 4 → Task 5 → Task 6 (sequencial dentro do agente)

Round 2 (após Round 1):
  Agente Backend-B: Task 7 → Task 8 (sequencial dentro do agente)
```

---

## Task 1 — Estender IncomingMessage (parser.py)

**Arquivo:** `backend/app/webhook/parser.py`  
**Dependências:** nenhuma

Adicionar dois campos opcionais ao dataclass `IncomingMessage` (linhas 4-16).

### Passo 1: Ler o arquivo

Ler `backend/app/webhook/parser.py` para confirmar o estado atual.

### Passo 2: Adicionar campos

Localizar:
```python
    push_name: str | None = None
    channel_id: str | None = None
```

Substituir por:
```python
    push_name: str | None = None
    channel_id: str | None = None
    document_name: str | None = None
    metadata: dict | None = None
```

### Passo 3: Verificar sintaxe

```bash
python -c "import ast; ast.parse(open('backend/app/webhook/parser.py').read()); print('OK')"
```

### Passo 4: Commit

```bash
git add backend/app/webhook/parser.py
git commit -m "feat(parser): adicionar document_name e metadata ao IncomingMessage"
```

---

## Task 2 — Novos tipos no meta_parser.py

**Arquivo:** `backend/app/webhook/meta_parser.py`  
**Dependências:** Task 1

Adicionar parsing de sticker, location, contacts, reaction. Capturar `filename` no document.

### Passo 1: Ler o arquivo

Ler `backend/app/webhook/meta_parser.py` completo.

### Passo 2: Adicionar variáveis locais no loop de mensagens

Localizar (linha ~33):
```python
                text = None
                media_url = None
                media_mime = None
                parsed_type = "text"
```

Substituir por:
```python
                text = None
                media_url = None
                media_mime = None
                document_name = None
                metadata_dict = None
                parsed_type = "text"
```

### Passo 3: Corrigir document para capturar filename

Localizar:
```python
                elif msg_type == "document":
                    parsed_type = "document"
                    doc = msg.get("document", {})
                    media_url = doc.get("id")
                    media_mime = doc.get("mime_type")
                    text = doc.get("caption")
```

Substituir por:
```python
                elif msg_type == "document":
                    parsed_type = "document"
                    doc = msg.get("document", {})
                    media_url = doc.get("id")
                    media_mime = doc.get("mime_type")
                    text = doc.get("caption")
                    document_name = doc.get("filename")
```

### Passo 4: Adicionar novos tipos antes do bloco `else:`

Localizar:
```python
                elif msg_type == "button":
```

Inserir ANTES dessa linha:

```python
                elif msg_type == "sticker":
                    parsed_type = "sticker"
                    sticker = msg.get("sticker", {})
                    media_url = sticker.get("id")
                    media_mime = sticker.get("mime_type")

                elif msg_type == "location":
                    parsed_type = "location"
                    loc = msg.get("location", {})
                    metadata_dict = {
                        "lat": loc.get("latitude"),
                        "lng": loc.get("longitude"),
                        "name": loc.get("name", ""),
                        "address": loc.get("address", ""),
                    }

                elif msg_type == "contacts":
                    parsed_type = "contact"
                    contacts_list = msg.get("contacts", [])
                    if contacts_list:
                        c = contacts_list[0]
                        name_obj = c.get("name", {})
                        phones = c.get("phones", [])
                        metadata_dict = {
                            "name": name_obj.get("formatted_name", ""),
                            "phone": phones[0].get("phone", "") if phones else "",
                            "vcard": c.get("vcard", ""),
                        }

                elif msg_type == "reaction":
                    parsed_type = "reaction"
                    reaction = msg.get("reaction", {})
                    metadata_dict = {
                        "emoji": reaction.get("emoji", ""),
                        "target_wamid": reaction.get("message_id", ""),
                    }

```

### Passo 5: Atualizar IncomingMessage construction

Localizar:
```python
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
                ))
```

Substituir por:
```python
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
                ))
```

### Passo 6: Verificar sintaxe

```bash
python -c "import ast; ast.parse(open('backend/app/webhook/meta_parser.py').read()); print('OK')"
```

### Passo 7: Commit

```bash
git add backend/app/webhook/meta_parser.py
git commit -m "feat(meta-parser): adicionar sticker, location, contact, reaction e document_name"
```

---

## Task 3 — buffer/manager.py + processor.py

**Arquivos:** `backend/app/buffer/manager.py`, `backend/app/buffer/processor.py`  
**Dependências:** Task 1, Task 2

### Parte A — manager.py

#### Passo 1: Ler o arquivo

Ler `backend/app/buffer/manager.py`.

#### Passo 2: Adicionar import json e corrigir _MEDIA_TYPES + META_TYPES

Localizar no topo do arquivo (após os imports existentes):
```python
from app.webhook.parser import IncomingMessage
```

Adicionar `import json` na linha anterior:
```python
import json
from app.webhook.parser import IncomingMessage
```

#### Passo 3: Substituir bloco de determinação de texto

Localizar (linhas ~27-34):
```python
    # Determine text content (will be resolved later for media)
    _MEDIA_TYPES = ("image", "video", "audio")
    if msg.media_url and msg.type in _MEDIA_TYPES:
        placeholder = f"[{msg.type}: media_url={msg.media_url}]"
        text = f"{msg.text}\n{placeholder}" if msg.text else placeholder
    elif msg.text:
        text = msg.text
    else:
        text = f"[{msg.type}: sem conteudo]"
```

Substituir por:
```python
    # Determine text content (will be resolved later for media)
    import base64 as _b64
    _MEDIA_TYPES = ("image", "video", "audio", "document", "sticker")
    _META_TYPES = ("location", "contact", "reaction")
    if msg.media_url and msg.type in _MEDIA_TYPES:
        if msg.type == "document" and msg.document_name:
            fname_b64 = _b64.b64encode(msg.document_name.encode()).decode()
            placeholder = f"[{msg.type}: media_url={msg.media_url} filename_b64={fname_b64}]"
        else:
            placeholder = f"[{msg.type}: media_url={msg.media_url}]"
        text = f"{msg.text}\n{placeholder}" if msg.text else placeholder
    elif msg.metadata and msg.type in _META_TYPES:
        meta_b64 = _b64.b64encode(json.dumps(msg.metadata).encode()).decode()
        text = f"[{msg.type}: meta_b64={meta_b64}]"
    elif msg.text:
        text = msg.text
    else:
        text = f"[{msg.type}: sem conteudo]"
```

#### Passo 4: Verificar sintaxe

```bash
python -c "import ast; ast.parse(open('backend/app/buffer/manager.py').read()); print('OK')"
```

#### Passo 5: Commit parcial

```bash
git add backend/app/buffer/manager.py
git commit -m "feat(buffer-manager): suporte a document, sticker e meta types no buffer"
```

---

### Parte B — processor.py

#### Passo 1: Ler o arquivo (linhas 1-10 para imports, depois 330-407 para _resolve_media)

Ler `backend/app/buffer/processor.py`.

#### Passo 2: Adicionar imports base64 e json

Localizar o bloco de imports no topo (linha 1):
```python
import asyncio
import os
import logging
import re
```

Substituir por:
```python
import asyncio
import base64
import json
import os
import logging
import re
```

#### Passo 3: Substituir a função _resolve_media completa

Localizar a assinatura da função (linha ~335):
```python
async def _resolve_media(text: str, provider) -> tuple[str, str | None, str | None]:
```

Substituir a função inteira `_resolve_media` (do `async def _resolve_media` até o `return text.strip(), storage_url, message_type` inclusive) por:

```python
async def _resolve_media(
    text: str, provider
) -> tuple[str, str | None, str | None, str | None, dict | None]:
    """Replace media placeholders with type/url metadata.

    Returns (resolved_text, media_url, message_type, document_name, metadata).
    Audio: downloaded, transcribed, uploaded to Supabase Storage.
    Image/video/document/sticker: media_id extracted only, no download.
    Location/contact/reaction: metadata dict extracted from base64 JSON.
    """
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"
    video_url_pattern = r"\[video: media_url=(\S+)\]"
    doc_url_pattern = r"\[document: media_url=(\S+?)(?:\s+filename_b64=([A-Za-z0-9+/=]+))?\]"
    sticker_url_pattern = r"\[sticker: media_url=(\S+)\]"
    meta_b64_pattern = r"\[(\w+): meta_b64=([A-Za-z0-9+/=]+)\]"

    storage_url: str | None = None
    message_type: str | None = None
    document_name: str | None = None
    metadata: dict | None = None

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            message_type = "audio"
            storage_url = media_ref

            try:
                audio_bytes, content_type = await provider.download_media(media_ref)
            except Exception as e:
                logger.warning(f"Failed to download audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")
                continue

            ext = "ogg" if "ogg" in content_type else "mp4"
            uploaded_url = _upload_audio_to_storage(audio_bytes, content_type, media_ref, ext)
            if uploaded_url:
                storage_url = uploaded_url

            try:
                transcript = await _get_openai().audio.transcriptions.create(
                    model="gemini-3-flash-preview",
                    file=(f"audio.{ext}", audio_bytes, content_type),
                )
                text = text.replace(match.group(0), f"[audio transcrito: {transcript.text}]")
            except Exception as e:
                logger.warning(f"Failed to transcribe audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_url_pattern, text):
        media_ref = match.group(1)
        if message_type is None:
            message_type = "image"
            storage_url = media_ref
        text = text.replace(match.group(0), "")

    for match in re.finditer(video_url_pattern, text):
        media_ref = match.group(1)
        if message_type is None:
            message_type = "video"
            storage_url = media_ref
        text = text.replace(match.group(0), "")

    for match in re.finditer(doc_url_pattern, text):
        media_ref = match.group(1)
        fname_b64 = match.group(2)
        if message_type is None:
            message_type = "document"
            storage_url = media_ref
            if fname_b64:
                try:
                    document_name = base64.b64decode(fname_b64).decode()
                except Exception:
                    pass
        text = text.replace(match.group(0), "")

    for match in re.finditer(sticker_url_pattern, text):
        media_ref = match.group(1)
        if message_type is None:
            message_type = "sticker"
            storage_url = media_ref
        text = text.replace(match.group(0), "")

    for match in re.finditer(meta_b64_pattern, text):
        meta_type = match.group(1)
        if meta_type in ("location", "contact", "reaction") and message_type is None:
            try:
                metadata = json.loads(base64.b64decode(match.group(2)).decode())
                message_type = meta_type
            except Exception as e:
                logger.warning(f"Failed to decode metadata for {meta_type}: {e}")
        text = text.replace(match.group(0), "")

    return text.strip(), storage_url, message_type, document_name, metadata
```

#### Passo 4: Atualizar chamada de _resolve_media em process_buffered_messages

Localizar (linhas ~158-163):
```python
    _media_url: str | None = None
    _message_type: str | None = None
    try:
        resolved_text, _media_url, _message_type = await _resolve_media(combined_text, provider)
    except Exception as e:
        logger.warning(f"Failed to resolve media for {phone}: {e}")
        resolved_text = combined_text
```

Substituir por:
```python
    _media_url: str | None = None
    _message_type: str | None = None
    _document_name: str | None = None
    _metadata: dict | None = None
    try:
        resolved_text, _media_url, _message_type, _document_name, _metadata = await _resolve_media(combined_text, provider)
    except Exception as e:
        logger.warning(f"Failed to resolve media for {phone}: {e}")
        resolved_text = combined_text
```

#### Passo 5: Passar novos campos ao save_message

Localizar (linhas ~181-188):
```python
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
        )
```

Substituir por:
```python
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
            document_name=_document_name,
            metadata=_metadata,
        )
```

#### Passo 6: Verificar sintaxe

```bash
python -c "import ast; ast.parse(open('backend/app/buffer/processor.py').read()); print('OK')"
```

#### Passo 7: Commit

```bash
git add backend/app/buffer/processor.py
git commit -m "feat(processor): suporte a document, sticker, location, contact, reaction"
```

---

## Task 4 — lib/types.ts (Frontend)

**Arquivo:** `frontend/src/lib/types.ts`  
**Dependências:** nenhuma (pode rodar em paralelo com Tasks 1-3)

> **OBRIGATÓRIO:** Invocar a skill `frontend-design` antes de implementar.

### Passo 1: Invocar skill frontend-design

### Passo 2: Ler o arquivo

### Passo 3: Adicionar campos à interface Message

Localizar:
```typescript
export interface Message {
  id: string;
  lead_id: string;
  role: string;       // "user" | "assistant" | "system"
  content: string;
  stage: string | null;
  sent_by: string;    // "agent" | "seller" | "cadence" | "user"
  created_at: string;
  message_type?: string;
  media_url?: string;
  wamid?: string | null;
  delivery_status?: "sent" | "delivered" | "read" | null;
}
```

Substituir por:
```typescript
export interface Message {
  id: string;
  lead_id: string;
  role: string;       // "user" | "assistant" | "system"
  content: string;
  stage: string | null;
  sent_by: string;    // "agent" | "seller" | "cadence" | "user"
  created_at: string;
  message_type?: string;
  media_url?: string;
  document_name?: string | null;
  media_mime?: string | null;
  metadata?: Record<string, unknown> | null;
  wamid?: string | null;
  delivery_status?: "sent" | "delivered" | "read" | null;
}
```

### Passo 4: Verificar TypeScript

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

### Passo 5: Commit

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(types): adicionar document_name, media_mime, metadata ao Message"
```

---

## Task 5 — /api/media/route.ts (Frontend)

**Arquivo:** `frontend/src/app/api/media/route.ts`  
**Dependências:** nenhuma

> **OBRIGATÓRIO:** Invocar a skill `frontend-design` antes de implementar.

### Passo 1: Invocar skill frontend-design

### Passo 2: Ler o arquivo

### Passo 3: Adicionar suporte a ?download=1&filename=xxx

Localizar:
```typescript
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const mediaId = searchParams.get("media_id");
  const conversationId = searchParams.get("conversation_id");

  if (!mediaId || !conversationId) {
    return NextResponse.json({ error: "Missing media_id or conversation_id" }, { status: 400 });
  }
```

Substituir por:
```typescript
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const mediaId = searchParams.get("media_id");
  const conversationId = searchParams.get("conversation_id");
  const download = searchParams.get("download") === "1";
  const filename = searchParams.get("filename");

  if (!mediaId || !conversationId) {
    return NextResponse.json({ error: "Missing media_id or conversation_id" }, { status: 400 });
  }
```

Localizar o return final:
```typescript
  return new Response(audioRes.body, {
    headers: {
      "Content-Type": mimeType,
      "Cache-Control": "private, max-age=86400",
    },
  });
```

Substituir por:
```typescript
  const responseHeaders: Record<string, string> = {
    "Content-Type": mimeType,
    "Cache-Control": "private, max-age=86400",
  };
  if (download && filename) {
    responseHeaders["Content-Disposition"] = `attachment; filename="${filename}"`;
  }

  return new Response(audioRes.body, { headers: responseHeaders });
```

### Passo 4: Verificar TypeScript

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

### Passo 5: Commit

```bash
git add frontend/src/app/api/media/route.ts
git commit -m "feat(media-proxy): suporte a download com Content-Disposition attachment"
```

---

## Task 6 — message-bubble.tsx (Frontend)

**Arquivo:** `frontend/src/components/conversas/message-bubble.tsx`  
**Dependências:** Tasks 4, 5

> **OBRIGATÓRIO:** Invocar a skill `frontend-design` antes de implementar.

### Passo 1: Invocar skill frontend-design

### Passo 2: Ler o arquivo completo

### Passo 3: Adicionar flags de tipo

Localizar:
```typescript
  const isAudio = message.message_type === "audio";
  const isImage = message.message_type === "image";
  const isDocument = message.message_type === "document";
  const isVideo = message.message_type === "video";
```

Substituir por:
```typescript
  const isAudio = message.message_type === "audio";
  const isImage = message.message_type === "image";
  const isDocument = message.message_type === "document";
  const isVideo = message.message_type === "video";
  const isSticker = message.message_type === "sticker";
  const isLocation = message.message_type === "location";
  const isContact = message.message_type === "contact";
  const isReaction = message.message_type === "reaction";
```

### Passo 4: Substituir o bloco isDocument para adicionar download

Localizar o bloco isDocument:
```typescript
        ) : isDocument ? (
          <div className="flex items-center gap-2 py-1">
            <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
            </svg>
            <span className="text-[13px] truncate max-w-[180px]">
              {message.content || "Documento"}
            </span>
          </div>
```

Substituir por:
```typescript
        ) : isDocument ? (
          <div className="flex items-center gap-2 py-1">
            <svg className="w-5 h-5 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
            </svg>
            <div className="flex flex-col min-w-0">
              <span className="text-[13px] truncate max-w-[180px]">
                {message.document_name || message.content || "Documento"}
              </span>
              {mediaSrc && (
                <a
                  href={`${mediaSrc.replace("/api/media?", "/api/media?download=1&filename=${encodeURIComponent(message.document_name || 'documento')}&")}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5"
                >
                  Baixar
                </a>
              )}
            </div>
          </div>
```

**Nota importante:** A URL de download deve ser construída adicionando `download=1` e `filename=` como query params. Revise a lógica de construção da URL para garantir que os parâmetros sejam adicionados corretamente à URL do mediaSrc já existente (que pode já ter `media_id` e `conversation_id`). Use `URL` ou `URLSearchParams` se necessário para construção segura.

### Passo 5: Adicionar renderers de sticker, location, contact, reaction ANTES do bloco de texto padrão

Localizar o bloco final (texto padrão):
```typescript
        ) : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
```

Substituir por:
```typescript
        ) : isSticker ? (
          mediaSrc ? (
            <img
              src={mediaSrc}
              alt="Sticker"
              className="max-w-[160px] max-h-[160px] object-contain block"
              onError={() => setImgError(true)}
            />
          ) : (
            <span className="text-[13px] opacity-60">Sticker</span>
          )
        ) : isLocation ? (
          (() => {
            const lat = (message.metadata as Record<string, unknown> | undefined)?.lat as number | undefined;
            const lng = (message.metadata as Record<string, unknown> | undefined)?.lng as number | undefined;
            const name = (message.metadata as Record<string, unknown> | undefined)?.name as string | undefined;
            const address = (message.metadata as Record<string, unknown> | undefined)?.address as string | undefined;
            const mapsUrl = lat !== undefined && lng !== undefined
              ? `https://maps.google.com/?q=${lat},${lng}`
              : null;
            return (
              <div className="flex items-start gap-2 py-1">
                <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-red-500" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
                </svg>
                <div className="flex flex-col min-w-0">
                  {(name || address) && (
                    <span className="text-[13px]">{name || address}</span>
                  )}
                  {mapsUrl && (
                    <a
                      href={mapsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5"
                    >
                      Ver no mapa
                    </a>
                  )}
                </div>
              </div>
            );
          })()
        ) : isContact ? (
          (() => {
            const name = (message.metadata as Record<string, unknown> | undefined)?.name as string | undefined;
            const phone = (message.metadata as Record<string, unknown> | undefined)?.phone as string | undefined;
            const vcard = (message.metadata as Record<string, unknown> | undefined)?.vcard as string | undefined;
            const vcardUrl = vcard
              ? `data:text/vcard;charset=utf-8,${encodeURIComponent(vcard)}`
              : null;
            return (
              <div className="flex items-start gap-2 py-1">
                <svg className="w-4 h-4 mt-0.5 flex-shrink-0 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM12 14a7 7 0 0 0-7 7h14a7 7 0 0 0-7-7z"/>
                </svg>
                <div className="flex flex-col min-w-0">
                  {name && <span className="text-[13px] font-medium">{name}</span>}
                  {phone && <span className="text-[12px] opacity-70">{phone}</span>}
                  {vcardUrl && (
                    <a
                      href={vcardUrl}
                      download={`${name || "contato"}.vcf`}
                      className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5"
                    >
                      Baixar contato
                    </a>
                  )}
                </div>
              </div>
            );
          })()
        ) : isReaction ? (
          (() => {
            const emoji = (message.metadata as Record<string, unknown> | undefined)?.emoji as string | undefined;
            return (
              <span className="text-[13px]">
                Reagiu: {emoji || "?"}
              </span>
            );
          })()
        ) : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
```

### Passo 6: Verificar TypeScript

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Corrigir qualquer erro de tipo antes de commitar.

### Passo 7: Commit

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(message-bubble): renderers para sticker, location, contact, reaction e documento com download"
```

---

## Task 7 — conversations/service.py

**Arquivo:** `backend/app/conversations/service.py`  
**Dependências:** Task 3 (processor.py passa os novos campos)

### Passo 1: Ler o arquivo (linhas 113-155 são suficientes)

### Passo 2: Adicionar params e campos ao save_message

Localizar:
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
    if wamid is not None:
        msg["wamid"] = wamid
        msg["delivery_status"] = "sent"
```

Substituir por:
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
    if wamid is not None:
        msg["wamid"] = wamid
        msg["delivery_status"] = "sent"
    if document_name is not None:
        msg["document_name"] = document_name
    if media_mime is not None:
        msg["media_mime"] = media_mime
    if metadata is not None:
        msg["metadata"] = metadata
```

### Passo 3: Verificar sintaxe

```bash
python -c "import ast; ast.parse(open('backend/app/conversations/service.py').read()); print('OK')"
```

### Passo 4: Commit

```bash
git add backend/app/conversations/service.py
git commit -m "feat(service): adicionar document_name, media_mime, metadata ao save_message"
```

---

## Task 8 — Verificação Final

### Passo 1: TypeScript completo

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -20
```

Esperado: zero erros.

### Passo 2: Syntax check Python em todos os arquivos alterados

```bash
for f in backend/app/webhook/parser.py backend/app/webhook/meta_parser.py backend/app/buffer/manager.py backend/app/buffer/processor.py backend/app/conversations/service.py; do
  python -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done
```

Esperado: `OK` para cada arquivo.

### Passo 3: Commit final se tudo passar

```bash
git add -A
git status
```

Verificar que não há arquivos não-relacionados staged antes de commitar.

# Conversas Media Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **FRONTEND RULE:** Qualquer agente que tocar em arquivos do frontend DEVE usar a skill `frontend-design` antes de implementar.

**Goal:** Fazer imagens e vídeos enviados por leads aparecerem visualmente na página /conversas.

**Architecture:** Proxy-only — o `media_id` da Meta é salvo no banco, o proxy `/api/media` busca o URL temporário na Meta Graph API sob demanda e faz streaming ao browser. Nenhuma mídia é armazenada permanentemente.

**Tech Stack:** Python (FastAPI backend), Next.js App Router (TypeScript frontend), Meta WhatsApp Cloud API Graph v21.0, Supabase (só para leitura de `provider_config`).

---

## Files Touched

| Arquivo | Mudança |
|---|---|
| `backend/app/buffer/manager.py` | Sempre incluir placeholder de mídia, mesmo quando há caption |
| `backend/app/buffer/processor.py` | Reescrever loop de imagens (sem download), adicionar loop de vídeos, strip no resultado |
| `frontend/src/components/conversas/message-bubble.tsx` | Adicionar renderização `<video controls>` |
| `frontend/src/app/api/media/route.ts` | Corrigir fallback mime-type |

---

## Task 1: Corrigir `buffer/manager.py` para preservar `media_id` em mensagens com caption

**Files:**
- Modify: `backend/app/buffer/manager.py:26-32`

O bug atual: se uma imagem/vídeo tem legenda (`msg.text`), o buffer armazena só a legenda e o `media_id` é perdido. A correção: para tipos de mídia, sempre incluir o placeholder, com a legenda na frente se houver.

- [ ] **Step 1: Abrir e ler o arquivo**

Ler `backend/app/buffer/manager.py` linhas 19-47 para confirmar o estado atual.

- [ ] **Step 2: Substituir a lógica de codificação de texto**

Localizar este bloco (linhas 27-32):
```python
    # Determine text content (will be resolved later for media)
    if msg.text:
        text = msg.text
    elif msg.media_url:
        text = f"[{msg.type}: media_url={msg.media_url}]"
    else:
        text = f"[{msg.type}: sem conteudo]"
```

Substituir por:
```python
    # Determine text content (will be resolved later for media)
    _MEDIA_TYPES = ("image", "video", "audio", "document")
    if msg.media_url and msg.type in _MEDIA_TYPES:
        placeholder = f"[{msg.type}: media_url={msg.media_url}]"
        text = f"{msg.text}\n{placeholder}" if msg.text else placeholder
    elif msg.text:
        text = msg.text
    else:
        text = f"[{msg.type}: sem conteudo]"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/buffer/manager.py
git commit -m "fix(buffer): preserve media_id in buffer even when caption exists"
```

---

## Task 2: Reescrever loop de imagens e adicionar loop de vídeos em `processor.py`

**Files:**
- Modify: `backend/app/buffer/processor.py:1` (remover import base64)
- Modify: `backend/app/buffer/processor.py:329-403` (função `_resolve_media`)

**Diagnóstico:**
- Loop de imagens atual: baixa bytes, gera base64, chama Gemini para descrição, **nunca define `message_type` nem `storage_url`**. Tudo isso deve ser removido.
- Loop de vídeos: inexistente.
- Correção: substituir loop de imagens por extração simples de `media_ref`, adicionar loop de vídeos idêntico.

- [ ] **Step 1: Remover `import base64`**

Linha 3 atual: `import base64`

Remover essa linha. `base64` só era usado na descrição de imagem com Gemini, que estamos removendo.

- [ ] **Step 2: Reescrever `_resolve_media`**

Substituir a função inteira `_resolve_media` (linhas 329-403) por:

```python
async def _resolve_media(text: str, provider) -> tuple[str, str | None, str | None]:
    """Replace media placeholders with type/url metadata.

    Returns (resolved_text, media_ref, message_type).
    media_ref is the Meta media_id or direct URL, used as media_url in the DB.
    Audio is downloaded, transcribed, and uploaded to Supabase Storage.
    Images and videos: only media_ref is extracted — no download, no AI processing.
    """
    # Meta-style: [type: media_id=xxx]
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    image_id_pattern = r"\[image: media_id=(\S+)\]"
    video_id_pattern = r"\[video: media_id=(\S+)\]"

    # Evolution-style or captioned media: [type: media_url=xxx]
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"
    video_url_pattern = r"\[video: media_url=(\S+)\]"

    storage_url: str | None = None
    message_type: str | None = None

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)

            # Always mark as audio and store media_ref as fallback for proxy,
            # regardless of whether download/upload/transcription succeeds.
            message_type = "audio"
            storage_url = media_ref

            try:
                audio_bytes, content_type = await provider.download_media(media_ref)
            except Exception as e:
                logger.warning(f"Failed to download audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")
                continue

            ext = "ogg" if "ogg" in content_type else "mp4"

            # Try Supabase Storage for permanent URL; keep media_id fallback if it fails
            uploaded_url = _upload_audio_to_storage(audio_bytes, content_type, media_ref, ext)
            if uploaded_url:
                storage_url = uploaded_url

            # Transcribe for AI agent context
            try:
                transcript = await _get_openai().audio.transcriptions.create(
                    model="gemini-3-flash-preview",
                    file=(f"audio.{ext}", audio_bytes, content_type),
                )
                text = text.replace(match.group(0), f"[audio transcrito: {transcript.text}]")
            except Exception as e:
                logger.warning(f"Failed to transcribe audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for pattern in [image_id_pattern, image_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            message_type = "image"
            storage_url = media_ref
            text = text.replace(match.group(0), "")

    for pattern in [video_id_pattern, video_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            message_type = "video"
            storage_url = media_ref
            text = text.replace(match.group(0), "")

    return text.strip(), storage_url, message_type
```

**Pontos chave da mudança:**
- Loop de imagens: 3 linhas — sem download, sem Gemini, sem base64. Define `message_type = "image"`, `storage_url = media_ref`, remove o placeholder do texto.
- Loop de vídeos: idêntico ao de imagens, mas com `message_type = "video"` e padrões de vídeo.
- `text.strip()` no return remove espaços/newlines residuais após remoção de placeholders.

- [ ] **Step 3: Verificar que `base64` não é usado em nenhum outro lugar do arquivo**

```bash
grep -n "base64" backend/app/buffer/processor.py
```

Esperado: nenhuma linha encontrada.

- [ ] **Step 4: Verificar sintaxe Python**

```bash
python -c "import ast; ast.parse(open('backend/app/buffer/processor.py').read()); print('OK')"
```

Esperado: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/processor.py
git commit -m "fix(processor): imagens e videos sem download, message_type e media_url corretos"
```

---

## Task 3: Adicionar renderização de vídeo no `message-bubble.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

> **OBRIGATÓRIO:** Usar a skill `frontend-design` antes de implementar esta task.

- [ ] **Step 1: Invocar a skill `frontend-design`**

Usar o Skill tool com `skill: "frontend-design"` antes de qualquer implementação.

- [ ] **Step 2: Ler o arquivo atual**

Ler `frontend/src/components/conversas/message-bubble.tsx` inteiro para confirmar estado atual.

- [ ] **Step 3: Adicionar `isVideo` e `videoError` state**

Localizar (linha 21):
```typescript
  const [imgError, setImgError] = useState(false);
```

Substituir por:
```typescript
  const [imgError, setImgError] = useState(false);
  const [videoError, setVideoError] = useState(false);
```

Localizar (linha 27):
```typescript
  const isDocument = message.message_type === "document";
```

Substituir por:
```typescript
  const isDocument = message.message_type === "document";
  const isVideo = message.message_type === "video";
```

- [ ] **Step 4: Adicionar bloco de renderização de vídeo**

Localizar o início do bloco `isImage` (linha 62):
```typescript
        ) : isImage ? (
```

Adicionar o bloco de vídeo ANTES do bloco `isImage`. O resultado deve ficar:

```typescript
        ) : isVideo ? (
          mediaSrc ? (
            videoError ? (
              <div className="flex items-center gap-2 py-1">
                <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.069A1 1 0 0121 8.868v6.264a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <span className="text-[13px] opacity-60">Vídeo</span>
              </div>
            ) : (
              <video
                controls
                src={mediaSrc}
                className="max-w-[320px] max-h-[400px] rounded-[4px] block"
                onError={() => setVideoError(true)}
              />
            )
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.069A1 1 0 0121 8.868v6.264a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <span className="text-[13px] opacity-60">Vídeo</span>
            </div>
          )
        ) : isImage ? (
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros relacionados a `message-bubble.tsx`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(conversas): adicionar player de video inline no bubble de mensagem"
```

---

## Task 4: Corrigir fallback mime-type no proxy `/api/media`

**Files:**
- Modify: `frontend/src/app/api/media/route.ts:49,70`

O proxy tem `"audio/ogg"` como fallback para `mime_type` e uma mensagem de erro referindo "Audio". Como agora serve imagens e vídeos, corrigir para não confundir o browser.

> **OBRIGATÓRIO:** Usar a skill `frontend-design` antes de implementar esta task (frontend).

- [ ] **Step 1: Invocar a skill `frontend-design`**

Usar o Skill tool com `skill: "frontend-design"`.

- [ ] **Step 2: Corrigir fallback mime-type (linha 49)**

Localizar:
```typescript
  const mimeType = info.mime_type ?? "audio/ogg";
```

Substituir por:
```typescript
  const mimeType = info.mime_type ?? "application/octet-stream";
```

- [ ] **Step 3: Corrigir mensagem de erro e comentário (linha 65-71)**

Localizar:
```typescript
  // Step 2: Stream audio directly to client — avoids buffering in memory
  const audioRes = await fetch(downloadUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!audioRes.ok) {
    return NextResponse.json({ error: "Audio download failed" }, { status: 502 });
  }
```

Substituir por:
```typescript
  // Step 2: Stream media directly to client — avoids buffering in memory
  const audioRes = await fetch(downloadUrl, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!audioRes.ok) {
    return NextResponse.json({ error: "Media download failed" }, { status: 502 });
  }
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/media/route.ts
git commit -m "fix(media-proxy): corrigir fallback mime-type para servir imagens e videos"
```

---

## Verificação Final

Após todos os tasks, verificar o fluxo completo manualmente:

1. Enviar uma imagem para o número de WhatsApp do canal de desenvolvimento
2. Abrir `/conversas` e encontrar a conversa
3. Confirmar que a imagem aparece como `<img>` no bubble
4. Enviar um vídeo curto (até 5MB para teste rápido)
5. Confirmar que o vídeo aparece como `<video controls>` e é reproduzível
6. Confirmar que mensagens de texto existentes continuam normais
7. Confirmar que áudio existente continua funcionando

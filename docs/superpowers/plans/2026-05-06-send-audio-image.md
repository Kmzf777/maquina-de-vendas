# Send Audio & Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o vendedor envie áudio (gravado no browser ou via arquivo) e imagens (via arquivo) diretamente do chat em `/conversas`.

**Architecture:** Nova rota Next.js `POST /api/conversations/[id]/send-media` aceita `multipart/form-data`, faz upload para a Meta Media API, envia a mensagem via Meta Graph API e salva no banco. No frontend, `chat-view.tsx` ganha botões de microfone e clipe com preview antes do envio. `message-bubble.tsx` ganha suporte a renderização de imagens.

**Tech Stack:** Next.js 14 (App Router), TypeScript, Meta Graph API v21.0, MediaRecorder API (browser), Supabase JS.

---

## File Map

| Ação | Arquivo |
|------|---------|
| CREATE | `frontend/src/app/api/conversations/[id]/send-media/route.ts` |
| MODIFY | `frontend/src/components/conversas/message-bubble.tsx` |
| MODIFY | `frontend/src/components/conversas/chat-view.tsx` |

**Spec de referência:** `docs/superpowers/specs/2026-05-06-send-audio-image-design.md`

---

## Task 1: Nova rota API `/send-media`

**Files:**
- Create: `frontend/src/app/api/conversations/[id]/send-media/route.ts`

> **Nota:** O projeto não tem framework de testes frontend configurado. A verificação é feita via `npm run type-check` e teste manual.

- [ ] **Step 1: Criar a rota**

Criar o arquivo `frontend/src/app/api/conversations/[id]/send-media/route.ts` com o conteúdo abaixo. O padrão segue `send/route.ts` existente (mesma forma de buscar conversa/canal, mesma função `sendViaMeta`-style).

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

const META_API_VERSION = "v21.0";
const MAX_FILE_SIZE = 16 * 1024 * 1024; // 16MB

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json({ error: "Invalid form data" }, { status: 400 });
  }

  const file = formData.get("file") as File | null;
  if (!file) {
    return NextResponse.json({ error: "file is required" }, { status: 400 });
  }

  if (file.size > MAX_FILE_SIZE) {
    return NextResponse.json(
      { error: "Arquivo muito grande (máx 16MB)" },
      { status: 400 }
    );
  }

  const mimeType = file.type;
  let messageType: "audio" | "image";
  if (mimeType.startsWith("audio/")) {
    messageType = "audio";
  } else if (mimeType.startsWith("image/")) {
    messageType = "image";
  } else {
    return NextResponse.json(
      { error: "Tipo de arquivo não suportado. Use áudio ou imagem." },
      { status: 400 }
    );
  }

  const supabase = await getServiceSupabase();

  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("*, leads(id, phone), channels(id, provider, provider_config)")
    .eq("id", conversationId)
    .single();

  if (convError || !conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  const channel = conv.channels as {
    id: string;
    provider: string;
    provider_config: Record<string, string>;
  } | null;
  const lead = conv.leads as { id: string; phone: string } | null;

  if (!channel || !lead?.phone) {
    return NextResponse.json({ error: "Invalid conversation data" }, { status: 400 });
  }

  if (channel.provider !== "meta_cloud") {
    return NextResponse.json(
      { error: "Envio de mídia disponível apenas para Meta Cloud" },
      { status: 400 }
    );
  }

  const { phone_number_id, access_token, api_version } = channel.provider_config;
  const version = api_version || META_API_VERSION;

  try {
    // Step 1: Upload to Meta Media API
    const uploadForm = new FormData();
    uploadForm.append("file", file);
    uploadForm.append("messaging_product", "whatsapp");
    uploadForm.append("type", mimeType);

    const uploadResp = await fetch(
      `https://graph.facebook.com/${version}/${phone_number_id}/media`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}` },
        body: uploadForm,
      }
    );

    if (!uploadResp.ok) {
      const err = await uploadResp.text();
      console.error("[send-media] Meta upload failed:", err);
      return NextResponse.json(
        { error: "Falha ao enviar arquivo para WhatsApp" },
        { status: 502 }
      );
    }

    const { id: mediaId } = (await uploadResp.json()) as { id: string };

    // Step 2: Send message via Meta Graph API
    const sendPayload = {
      messaging_product: "whatsapp",
      to: lead.phone,
      type: messageType,
      [messageType]: { id: mediaId },
    };

    const sendResp = await fetch(
      `https://graph.facebook.com/${version}/${phone_number_id}/messages`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(sendPayload),
      }
    );

    if (!sendResp.ok) {
      const err = await sendResp.text();
      console.error("[send-media] Meta send failed:", err);
      return NextResponse.json(
        { error: "Falha ao enviar mensagem" },
        { status: 502 }
      );
    }

    // Step 3: Save to DB
    await supabase.from("messages").insert({
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: "",
      sent_by: "seller",
      message_type: messageType,
      media_url: mediaId,
    });

    await supabase
      .from("conversations")
      .update({
        unread_count: 0,
        last_msg_at: new Date().toISOString(),
      })
      .eq("id", conversationId);

    return NextResponse.json({ status: "sent" });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send media";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
```

- [ ] **Step 2: Verificar tipagem**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check
```

Esperado: zero erros de TypeScript.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/conversations/[id]/send-media/route.ts
git commit -m "feat(api): rota send-media para envio de áudio e imagem via Meta Cloud"
```

---

## Task 2: message-bubble.tsx — Renderização de imagem

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

> Esta task é independente da Task 1 e pode ser executada em paralelo.

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat /home/rafael/maquinadevendas/frontend/src/components/conversas/message-bubble.tsx
```

- [ ] **Step 2: Fazer as alterações**

Há três mudanças:

**Mudança A** — Renomear `audioSrc` para `mediaSrc` e adicionar `isImage`:

Substituir o bloco:
```tsx
  const isAudio = message.message_type === "audio";

  // New messages: media_url is a Supabase Storage URL (https://...)
  // Legacy messages: media_url is a Meta media_id (numeric string) — use proxy fallback
  const audioSrc = message.media_url
    ? message.media_url.startsWith("http")
      ? message.media_url
      : `/api/media?media_id=${encodeURIComponent(message.media_url)}&conversation_id=${encodeURIComponent(conversationId)}`
    : null;
```

Por:
```tsx
  const isAudio = message.message_type === "audio";
  const isImage = message.message_type === "image";

  // New messages: media_url is a Supabase Storage URL (https://...) or object URL (blob:...)
  // Legacy messages: media_url is a Meta media_id (numeric string) — use proxy fallback
  const mediaSrc = message.media_url
    ? message.media_url.startsWith("http") || message.media_url.startsWith("blob:")
      ? message.media_url
      : `/api/media?media_id=${encodeURIComponent(message.media_url)}&conversation_id=${encodeURIComponent(conversationId)}`
    : null;
```

**Mudança B** — No JSX, substituir o bloco de renderização de conteúdo.

Substituir:
```tsx
        {isAudio ? (
          audioSrc ? (
            <audio
              controls
              src={audioSrc}
              className="h-10 max-w-[240px]"
            />
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
```

(o bloco completo até o `<p>` de texto)

Por (bloco completo novo — copie exatamente):
```tsx
        {isAudio ? (
          mediaSrc ? (
            <audio
              controls
              src={mediaSrc}
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
        ) : isImage ? (
          mediaSrc ? (
            <img
              src={mediaSrc}
              alt="imagem"
              className="max-w-[240px] rounded-[4px] block"
            />
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 0 1 2.828 0L16 16m-2-2l1.586-1.586a2 2 0 0 1 2.828 0L20 14m-6-6h.01M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
              </svg>
              <span className="text-[13px] opacity-60">Imagem</span>
            </div>
          )
        ) : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
```

- [ ] **Step 3: Verificar tipagem**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check
```

Esperado: zero erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(ui): renderizar imagens no message-bubble"
```

---

## Task 3: chat-view.tsx — Clip button + file upload + recording UI

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

> Depende da Task 1 (usa o endpoint `/send-media`).

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat /home/rafael/maquinadevendas/frontend/src/components/conversas/chat-view.tsx
```

- [ ] **Step 2: Adicionar imports e refs no topo do componente**

Após a linha `import { useState, useEffect, useRef, useMemo } from "react";`, adicionar `ChangeEvent` ao import:

```tsx
import { useState, useEffect, useRef, useMemo, type ChangeEvent } from "react";
```

- [ ] **Step 3: Adicionar novos estados e refs**

Dentro do componente `ChatView`, após a linha `const abortRef = useRef<AbortController | null>(null);`, adicionar:

```tsx
  // Media states
  const [mediaState, setMediaState] = useState<'idle' | 'recording' | 'previewing' | 'sendingMedia'>('idle');
  const [mediaBlob, setMediaBlob] = useState<Blob | null>(null);
  const [mediaObjectUrl, setMediaObjectUrl] = useState<string | null>(null);
  const [mediaMessageType, setMediaMessageType] = useState<'audio' | 'image' | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
```

- [ ] **Step 4: Adicionar funções de mídia**

Após a função `handleKeyDown`, antes do `return (`, adicionar:

```tsx
  function cancelMedia() {
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    setMediaBlob(null);
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/ogg')
        ? 'audio/ogg'
        : '';

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const objectUrl = URL.createObjectURL(blob);
        setMediaBlob(blob);
        setMediaObjectUrl(objectUrl);
        setMediaMessageType('audio');
        setMediaState('previewing');
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      };

      recorder.start();
      setRecordingSeconds(0);
      setMediaState('recording');
      recordingTimerRef.current = setInterval(() => setRecordingSeconds(s => s + 1), 1000);
    } catch {
      // User denied microphone access or browser not supported
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  function handleFileSelect(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const MAX_SIZE = 16 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      alert('Arquivo muito grande. Máximo 16MB.');
      e.target.value = '';
      return;
    }

    const type = file.type.startsWith('audio/') ? 'audio'
      : file.type.startsWith('image/') ? 'image'
      : null;

    if (!type) {
      alert('Tipo não suportado. Use áudio ou imagem.');
      e.target.value = '';
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setMediaBlob(file);
    setMediaObjectUrl(objectUrl);
    setMediaMessageType(type);
    setMediaState('previewing');
    e.target.value = '';
  }

  async function handleSendMedia() {
    if (!mediaBlob || !mediaMessageType || !mediaObjectUrl) return;

    setMediaState('sendingMedia');

    const tempMsg: Message = {
      id: `temp_media_${Date.now()}`,
      lead_id: lead?.id ?? '',
      role: 'assistant',
      content: '',
      stage: null,
      sent_by: 'seller',
      created_at: new Date().toISOString(),
      message_type: mediaMessageType,
      media_url: mediaObjectUrl,
    };
    setOptimisticMessages(prev => [...prev, tempMsg]);

    const blobToSend = mediaBlob;
    const urlToRevoke = mediaObjectUrl;
    const typeToSend = mediaMessageType;

    setMediaBlob(null);
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');

    try {
      const fd = new FormData();
      const filename = typeToSend === 'audio' ? 'audio.webm' : 'image.jpg';
      fd.append('file', blobToSend, filename);

      const res = await fetch(`/api/conversations/${conversation.id}/send-media`, {
        method: 'POST',
        body: fd,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({ error: 'Falha ao enviar' }));
        alert(data.error || 'Falha ao enviar');
      }
    } finally {
      setOptimisticMessages(prev => prev.filter(m => m.id !== tempMsg.id));
      URL.revokeObjectURL(urlToRevoke);
    }
  }
```

- [ ] **Step 5: Atualizar o useEffect de reset de conversa**

Localizar o effect que reseta estado ao mudar de conversa:

```tsx
  useEffect(() => {
    setOptimisticMessages([]);
    setShowTemplateModal(false);
    setDispatchSuccess(false);
  }, [conversation.id]);
```

Substituir por:

```tsx
  useEffect(() => {
    setOptimisticMessages([]);
    setShowTemplateModal(false);
    setDispatchSuccess(false);
    // Reset media state
    setMediaState('idle');
    setMediaBlob(null);
    setMediaMessageType(null);
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
  }, [conversation.id]);
```

Também adicionar cleanup de objectURL no effect de cleanup existente. Localizar:

```tsx
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, [conversation.id]);
```

Substituir por:

```tsx
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, [conversation.id]);
```

- [ ] **Step 6: Substituir o bloco do input bar no JSX**

Localizar o bloco que começa com `{/* Input or locked dispatch card */}` (quando `isInputBlocked` é false), especificamente a `<div>` do input normal:

```tsx
      ) : (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      )}
```

Substituir por:

```tsx
      ) : mediaState === 'previewing' || mediaState === 'sendingMedia' ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex flex-col gap-2 flex-shrink-0">
          {mediaMessageType === 'audio' && mediaObjectUrl && (
            <audio controls src={mediaObjectUrl} className="w-full h-10" />
          )}
          {mediaMessageType === 'image' && mediaObjectUrl && (
            <img src={mediaObjectUrl} alt="preview" className="max-h-40 rounded-[4px] object-contain self-start" />
          )}
          <div className="flex gap-2 justify-end">
            <button
              onClick={cancelMedia}
              disabled={mediaState === 'sendingMedia'}
              className="px-4 py-2 text-[13px] border border-[#dedbd6] rounded-[4px] text-[#111111] disabled:opacity-40"
            >
              Cancelar
            </button>
            <button
              onClick={handleSendMedia}
              disabled={mediaState === 'sendingMedia'}
              className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[13px] disabled:opacity-40"
            >
              {mediaState === 'sendingMedia' ? 'Enviando...' : 'Enviar'}
            </button>
          </div>
        </div>
      ) : mediaState === 'recording' ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex items-center gap-3 flex-shrink-0">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
          <span className="text-[13px] text-[#111111]">
            {String(Math.floor(recordingSeconds / 60)).padStart(2, '0')}:{String(recordingSeconds % 60).padStart(2, '0')}
          </span>
          <button
            onClick={stopRecording}
            className="ml-auto bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[13px]"
          >
            Parar
          </button>
        </div>
      ) : (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,image/*"
            onChange={handleFileSelect}
            className="hidden"
          />
          <button
            onClick={startRecording}
            disabled={isInputBlocked}
            title="Gravar áudio"
            className="text-[#7b7b78] hover:text-[#111111] disabled:opacity-40 flex-shrink-0 self-end pb-[9px]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
              <line x1="8" y1="23" x2="16" y2="23" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
            </svg>
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isInputBlocked}
            title="Anexar áudio ou imagem"
            className="text-[#7b7b78] hover:text-[#111111] disabled:opacity-40 flex-shrink-0 self-end pb-[9px]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 1 0 2.828 2.828l6.414-6.586a4 4 0 0 0-5.656-5.656l-6.415 6.585a6 6 0 1 0 8.486 8.486L20.5 13" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      )}
```

- [ ] **Step 7: Verificar tipagem**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check
```

Esperado: zero erros.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(ui): botões de microfone e clipe com preview para envio de mídia"
```

---

## Task 4: Validação manual E2E

> Depende das Tasks 1, 2 e 3 completas.

- [ ] **Step 1: Subir o ambiente de dev**

Usar a VS Code task `Run All Dev (CRM & Backend)` ou:

```bash
cd /home/rafael/maquinadevendas/frontend && npm run dev
```

- [ ] **Step 2: Testar envio de imagem via arquivo**

1. Abrir `/conversas` no browser
2. Selecionar uma conversa com canal `meta_cloud` e janela 24h aberta
3. Clicar no botão de clipe
4. Selecionar uma imagem JPG ou PNG (< 5MB)
5. Verificar que preview de imagem aparece no input bar
6. Clicar "Enviar"
7. Verificar que a imagem aparece no chat como bubble outbound
8. Verificar que o lead recebe a imagem no WhatsApp

- [ ] **Step 3: Testar envio de áudio via arquivo**

1. Clicar no botão de clipe
2. Selecionar um arquivo MP3 ou OGG
3. Preview de áudio aparece com player
4. Clicar "Enviar"
5. Bubble de áudio aparece no chat
6. Lead recebe o áudio no WhatsApp

- [ ] **Step 4: Testar gravação de áudio**

1. Clicar no botão de microfone
2. Permitir acesso ao microfone quando solicitado
3. Falar algo
4. Timer visível com segundos incrementando
5. Clicar "Parar"
6. Preview de áudio aparece com o áudio gravado
7. Ouvir o preview para confirmar qualidade
8. Clicar "Enviar"
9. Bubble aparece no chat
10. Lead recebe o áudio no WhatsApp

- [ ] **Step 5: Testar cancelamento**

1. Iniciar gravação → clicar "Parar" → na tela de preview clicar "Cancelar"
2. UI retorna ao estado normal de input
3. Repetir com arquivo: selecionar arquivo → clicar "Cancelar" → UI normal

- [ ] **Step 6: Testar arquivo inválido**

1. Clicar no clipe → selecionar um arquivo PDF
2. Alert deve aparecer: "Tipo não suportado. Use áudio ou imagem."
3. UI permanece no estado idle

- [ ] **Step 7: Testar janela fechada**

1. Abrir uma conversa com janela 24h expirada
2. Verificar que os botões de microfone e clipe estão com opacity-40 e não clicáveis
3. O card de "Janela encerrada" aparece normalmente

- [ ] **Step 8: Commit final (se nenhum ajuste foi necessário)**

```bash
git add -p  # staging seletivo se houver ajustes
git commit -m "fix(ui): ajustes de validação manual envio de mídia"
```

Se não houve ajustes, não é necessário commitar nada.

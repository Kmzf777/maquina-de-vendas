# Envio de Documentos em /conversas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **MANDATORY:** Any agent touching frontend files MUST invoke the `frontend-design` skill before making changes.

**Goal:** Permitir que vendedores enviem documentos (PDF, Word, Excel, PowerPoint, etc.) via WhatsApp pelo chat de /conversas, usando o provider Meta Cloud.

**Architecture:** Expandir o botão de clipe existente para aceitar documentos. O frontend detecta o tipo `document`, exibe um preview de nome/ícone, e envia para o endpoint `send-media` já existente. O backend detecta o tipo documento, aplica limite de 100MB, e envia via API Meta com `type: "document"`. O balão de mensagem renderiza ícone + nome do arquivo.

**Tech Stack:** Next.js App Router, TypeScript, Meta Graph API v21.0, Supabase.

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `frontend/src/components/conversas/chat-view.tsx` | Modificar | Input accept, detecção de tipo document, preview, limite 100MB |
| `frontend/src/app/api/conversations/[id]/send-media/route.ts` | Modificar | Suporte ao tipo document, limite por tipo, payload Meta |
| `frontend/src/components/conversas/message-bubble.tsx` | Modificar | Renderização do balão de documento |

---

## Task 1: Backend — suporte a document no send-media

**Files:**
- Modify: `frontend/src/app/api/conversations/[id]/send-media/route.ts`

- [ ] **Step 1: Adicionar constante de limite para documentos**

Em `send-media/route.ts`, substituir a linha:
```ts
const MAX_FILE_SIZE = 16 * 1024 * 1024; // 16MB
```
Por:
```ts
const MAX_SIZE_MEDIA = 16 * 1024 * 1024;   // 16MB — áudio e imagem
const MAX_SIZE_DOCUMENT = 100 * 1024 * 1024; // 100MB — documentos
```

- [ ] **Step 2: Ampliar detecção de messageType para document**

Localizar o bloco de detecção de tipo (linha ~84):
```ts
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
```
Substituir por:
```ts
let messageType: "audio" | "image" | "document";
if (mimeType.startsWith("audio/")) {
  messageType = "audio";
} else if (mimeType.startsWith("image/")) {
  messageType = "image";
} else {
  messageType = "document";
}
```

- [ ] **Step 3: Aplicar limite de tamanho correto por tipo**

O check de tamanho acontece antes da detecção do tipo (linha ~72). Mover a checagem para depois da detecção, ou substituir a checagem existente por uma condicional. Substituir o bloco:
```ts
if (file.size > MAX_FILE_SIZE) {
  return NextResponse.json(
    { error: "Arquivo muito grande (máx 16MB)" },
    { status: 400 }
  );
}
```
Por (colocar após a detecção de `messageType`):
```ts
const maxSize = messageType === "document" ? MAX_SIZE_DOCUMENT : MAX_SIZE_MEDIA;
if (file.size > maxSize) {
  const limitLabel = messageType === "document" ? "100MB" : "16MB";
  return NextResponse.json(
    { error: `Arquivo muito grande (máx ${limitLabel})` },
    { status: 400 }
  );
}
```
Remover o check de tamanho antigo (o `if (file.size > MAX_FILE_SIZE)` original).

- [ ] **Step 4: Ler o filename original do FormData**

Após a linha que lê `const file = formData.get("file") as File | null;`, adicionar:
```ts
const originalFilename = (formData.get("filename") as string | null) ?? file?.name ?? "documento";
```

- [ ] **Step 5: Adicionar payload Meta para document no sendPayload**

Localizar o bloco que monta `sendPayload` (linha ~176):
```ts
const sendPayload = {
  messaging_product: "whatsapp",
  to: lead.phone,
  type: messageType,
  [messageType]: { id: mediaId },
};
```
Substituir por:
```ts
const mediaBody =
  messageType === "document"
    ? { id: mediaId, filename: originalFilename }
    : { id: mediaId };

const sendPayload = {
  messaging_product: "whatsapp",
  to: lead.phone,
  type: messageType,
  [messageType]: mediaBody,
};
```

- [ ] **Step 6: Salvar content com nome do arquivo no DB**

Localizar o insert no Supabase (linha ~205):
```ts
await supabase.from("messages").insert({
  lead_id: lead.id,
  conversation_id: conversationId,
  role: "assistant",
  content: "",
  sent_by: "seller",
  message_type: messageType,
  media_url: mediaId,
});
```
Substituir por:
```ts
await supabase.from("messages").insert({
  lead_id: lead.id,
  conversation_id: conversationId,
  role: "assistant",
  content: messageType === "document" ? originalFilename : "",
  sent_by: "seller",
  message_type: messageType,
  media_url: mediaId,
});
```

- [ ] **Step 7: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```
Esperado: sem erros.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/app/api/conversations/`[id`]/send-media/route.ts
git commit -m "feat(send-media): suporte a envio de documentos via Meta Cloud"
```

---

## Task 2: Frontend — chat-view.tsx (input e preview de documento)

> **MANDATORY:** Invocar skill `frontend-design` antes de qualquer edição nesta task.

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

Obrigatório antes de editar. Não pular.

- [ ] **Step 2: Ampliar o tipo de mediaMessageType para incluir 'document'**

Localizar a linha (linha ~44):
```ts
const [mediaMessageType, setMediaMessageType] = useState<'audio' | 'image' | null>(null);
```
Substituir por:
```ts
const [mediaMessageType, setMediaMessageType] = useState<'audio' | 'image' | 'document' | null>(null);
```

Localizar também a linha (~44):
```ts
const [mediaBlob, setMediaBlob] = useState<Blob | null>(null);
```
Adicionar logo abaixo um estado para o nome do arquivo:
```ts
const [mediaFilename, setMediaFilename] = useState<string>("");
```

- [ ] **Step 3: Atualizar o cancelMedia para limpar mediaFilename**

Localizar a função `cancelMedia` e adicionar:
```ts
setMediaFilename("");
```
Junto aos outros resets de estado.

- [ ] **Step 4: Atualizar o reset no useEffect de conversation.id**

Localizar o `useEffect` que faz reset ao trocar de conversa (linha ~56) e adicionar:
```ts
setMediaFilename("");
```
Junto aos outros resets.

- [ ] **Step 5: Atualizar handleFileSelect para aceitar documentos**

Localizar o bloco de detecção de tipo em `handleFileSelect` (linha ~213):
```ts
const type = file.type.startsWith('audio/') ? 'audio'
  : file.type.startsWith('image/') ? 'image'
  : null;

if (!type) {
  alert('Tipo não suportado. Use áudio ou imagem.');
  e.target.value = '';
  return;
}
```
Substituir por:
```ts
const type: 'audio' | 'image' | 'document' =
  file.type.startsWith('audio/') ? 'audio'
  : file.type.startsWith('image/') ? 'image'
  : 'document';
```

Localizar a checagem de tamanho logo acima (linha ~206):
```ts
const MAX_SIZE = 16 * 1024 * 1024;
if (file.size > MAX_SIZE) {
  alert('Arquivo muito grande. Máximo 16MB.');
  e.target.value = '';
  return;
}
```
Substituir por:
```ts
const MAX_SIZE = type === 'document' ? 100 * 1024 * 1024 : 16 * 1024 * 1024;
const MAX_LABEL = type === 'document' ? '100MB' : '16MB';
if (file.size > MAX_SIZE) {
  alert(`Arquivo muito grande. Máximo ${MAX_LABEL}.`);
  e.target.value = '';
  return;
}
```
Nota: a detecção de tipo precisa ocorrer antes da checagem de tamanho. Reordenar se necessário.

Após definir `objectUrl`, adicionar:
```ts
setMediaFilename(file.name);
```

- [ ] **Step 6: Capturar filename e atualizar handleSendMedia**

No início de `handleSendMedia`, logo antes das declarações de `blobToSend`/`urlToRevoke`/`typeToSend`, adicionar a captura do filename:
```ts
const capturedFilename = mediaFilename;
```

Adicionar `setMediaFilename("")` junto aos outros resets de estado (`setMediaBlob(null)`, etc.).

Atualizar o `tempMsg` para incluir o content no caso de documento — `tempMsg` continua no mesmo lugar, agora usando `capturedFilename`:
```ts
const tempMsg: Message = {
  id: `temp_media_${Date.now()}`,
  lead_id: lead?.id ?? '',
  role: 'assistant',
  content: mediaMessageType === 'document' ? capturedFilename : '',
  stage: null,
  sent_by: 'seller',
  created_at: new Date().toISOString(),
  message_type: mediaMessageType,
  media_url: mediaObjectUrl,
};
```

No bloco `try`, substituir o FormData:
```ts
const fd = new FormData();
const filenameToSend = capturedFilename || (
  typeToSend === 'audio' ? 'audio.webm'
  : typeToSend === 'image' ? 'image.jpg'
  : 'documento'
);
fd.append('file', blobToSend, filenameToSend);
fd.append('filename', filenameToSend);
```
Remover as linhas antigas de `ext` e `filename`.

- [ ] **Step 7: Adicionar preview de documento na área de preview**

Localizar o bloco de preview (linha ~347):
```tsx
{mediaMessageType === 'audio' && mediaObjectUrl && (
  <audio controls src={mediaObjectUrl} className="w-full h-10" />
)}
{mediaMessageType === 'image' && mediaObjectUrl && (
  <img src={mediaObjectUrl} alt="preview" className="max-h-40 rounded-[4px] object-contain self-start" />
)}
```
Adicionar após o bloco de imagem:
```tsx
{mediaMessageType === 'document' && (
  <div className="flex items-center gap-2 py-1 px-2 bg-white border border-[#dedbd6] rounded-[6px] self-start max-w-full">
    <svg className="w-5 h-5 flex-shrink-0 text-[#7b7b78]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
    </svg>
    <span className="text-[13px] text-[#111111] truncate max-w-[220px]">
      {mediaFilename || "Documento"}
    </span>
  </div>
)}
```

- [ ] **Step 8: Atualizar o accept do input de arquivo**

Localizar (linha ~388):
```tsx
accept="audio/*,image/*"
```
Substituir por:
```tsx
accept="audio/*,image/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
```

- [ ] **Step 9: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```
Esperado: sem erros.

- [ ] **Step 10: Commit**

```powershell
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(conversas): suporte a envio de documentos no input de chat"
```

---

## Task 3: Frontend — message-bubble.tsx (balão de documento)

> **MANDATORY:** Invocar skill `frontend-design` antes de qualquer edição nesta task.

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

- [ ] **Step 1: Invocar skill frontend-design**

Obrigatório antes de editar. Não pular.

- [ ] **Step 2: Adicionar detecção de isDocument**

Localizar (linha ~24):
```ts
const isAudio = message.message_type === "audio";
const isImage = message.message_type === "image";
```
Adicionar:
```ts
const isDocument = message.message_type === "document";
```

- [ ] **Step 3: Renderizar o balão de documento**

No bloco de renderização condicional do conteúdo, localizar o último `else` (linha ~86):
```tsx
} : (
  <p className="whitespace-pre-wrap break-words">{message.content}</p>
)}
```
O bloco completo atual é:
```tsx
{isAudio ? (
  ...
) : isImage ? (
  ...
) : (
  <p className="whitespace-pre-wrap break-words">{message.content}</p>
)}
```
Expandir para:
```tsx
{isAudio ? (
  mediaSrc ? (
    <audio controls src={mediaSrc} className="h-10 max-w-[240px]" />
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
    imgError ? (
      <div className="flex items-center gap-2 py-1">
        <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 0 1 2.828 0L16 16m-2-2l1.586-1.586a2 2 0 0 1 2.828 0L20 14m-6-6h.01M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
        </svg>
        <span className="text-[13px] opacity-60">Imagem</span>
      </div>
    ) : (
      <img
        src={mediaSrc}
        alt="Imagem enviada"
        className="max-w-[240px] max-h-[320px] object-contain rounded-[4px] block"
        onError={() => setImgError(true)}
      />
    )
  ) : (
    <div className="flex items-center gap-2 py-1">
      <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 0 1 2.828 0L16 16m-2-2l1.586-1.586a2 2 0 0 1 2.828 0L20 14m-6-6h.01M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
      </svg>
      <span className="text-[13px] opacity-60">Imagem</span>
    </div>
  )
) : isDocument ? (
  <div className="flex items-center gap-2 py-1">
    <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
    </svg>
    <span className="text-[13px] truncate max-w-[180px]">
      {message.content || "Documento"}
    </span>
  </div>
) : (
  <p className="whitespace-pre-wrap break-words">{message.content}</p>
)}
```

- [ ] **Step 4: Verificar TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```
Esperado: sem erros.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(conversas): balão de documento no message-bubble"
```

---

## Task 4: Verificação manual end-to-end

- [ ] **Step 1: Subir o ambiente dev**

Usar a VS Code task `Run All Dev (CRM & Backend)` ou equivalente.

- [ ] **Step 2: Testar envio de PDF**

1. Abrir uma conversa de um lead com channel Meta Cloud e janela de 24h aberta.
2. Clicar no clipe (📎).
3. Selecionar um arquivo `.pdf` de até 100MB.
4. Verificar que o preview aparece: ícone de documento + nome do arquivo.
5. Clicar "Enviar".
6. Verificar que o balão aparece na conversa com ícone + nome do arquivo.
7. No WhatsApp do lead: verificar que o documento chegou com o nome correto.

- [ ] **Step 3: Testar envio de .docx**

Repetir o Step 2 com um arquivo `.docx`.

- [ ] **Step 4: Testar limite de tamanho**

Tentar enviar um arquivo > 100MB e verificar o alert correto.

- [ ] **Step 5: Regressão — imagem ainda funciona**

Enviar uma imagem e verificar que o fluxo existente não foi afetado.

- [ ] **Step 6: Regressão — áudio gravado ainda funciona**

Gravar um áudio e enviar. Verificar que funciona.

- [ ] **Step 7: Regressão — janela fechada ainda bloqueia**

Abrir uma conversa com janela fechada e verificar que o input permanece bloqueado.

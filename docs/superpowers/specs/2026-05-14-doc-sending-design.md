# Spec: Envio de Documentos em /conversas

**Data:** 2026-05-14  
**Status:** Aprovado

---

## Contexto

A tela `/conversas` já suporta envio de texto, áudio gravado e imagem/áudio por arquivo. Falta suporte a documentos (PDF, Word, Excel, PowerPoint, etc.) via WhatsApp.

---

## Escopo

- **Provider:** Meta Cloud apenas (mesma restrição do send-media atual).
- **Tipos aceitos:** PDF, Word (.doc/.docx), Excel (.xls/.xlsx), PowerPoint (.ppt/.pptx), e qualquer outro tipo que a Meta aceite como `document`.
- **Limite de tamanho:** 100MB (máximo aceito pela Meta para documentos).
- **Exibição no balão:** ícone de documento + nome do arquivo. Sem link de download.

Fora do escopo: Evolution API, vídeo, preview inline de PDF.

---

## Abordagem

Reutilizar o botão de clipe existente (`fileInputRef`). Expandir o `accept` do `<input type="file">` para incluir tipos de documento. Detectar o novo tipo `document` no `handleFileSelect`. Passar o tipo para o backend via `send-media`. Exibir o balão correto no `message-bubble`.

---

## Mudanças por camada

### 1. Frontend — `chat-view.tsx`

**`<input type="file">` accept:**
```
audio/*,image/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx
```

**`mediaMessageType` state:** ampliar de `'audio' | 'image' | null` para `'audio' | 'image' | 'document' | null`.

**`handleFileSelect`:**
- Remover o `alert` de "Tipo não suportado" para tipos desconhecidos — tratar qualquer MIME que não seja `audio/*` nem `image/*` como `document`.
- Limite de tamanho: manter 16MB para áudio/imagem; usar 100MB para documentos.
- Armazenar o `File` (não apenas Blob) para preservar `file.name`.

**Preview no input (antes de enviar):**
- Áudio: player `<audio>` (mantém).
- Imagem: thumbnail `<img>` (mantém).
- Documento: ícone de arquivo + `file.name` truncado + tamanho formatado.

**`handleSendMedia`:** sem mudança de lógica — já passa o blob para o endpoint. Garantir que o `filename` enviado no `FormData` preserve a extensão original (`file.name`).

### 2. API — `send-media/route.ts`

**Limite por tipo:**
```ts
const MAX_SIZE_DEFAULT = 16 * 1024 * 1024;  // 16MB — áudio e imagem
const MAX_SIZE_DOCUMENT = 100 * 1024 * 1024; // 100MB — documentos
```

**Detecção de tipo:**
```ts
if (mimeType.startsWith("audio/"))       messageType = "audio";
else if (mimeType.startsWith("image/"))  messageType = "image";
else                                      messageType = "document";
```

Aplicar o limite correto após detectar o tipo.

**Payload Meta para documentos:**
```json
{
  "messaging_product": "whatsapp",
  "to": "<phone>",
  "type": "document",
  "document": { "id": "<mediaId>", "filename": "<original_filename>" }
}
```

O `filename` vem do campo `file.name` do FormData. Extrair via `formData.get("filename")` (campo adicional) ou do nome do arquivo no FormData.

**Salvar no DB:**
```ts
await supabase.from("messages").insert({
  ...,
  message_type: "document",
  media_url: mediaId,
  content: file.name, // preserva o nome original para exibição
});
```

### 3. Frontend — `message-bubble.tsx`

Adicionar bloco `isDocument`:
```tsx
const isDocument = message.message_type === "document";
```

Renderização do balão de documento:
```tsx
<div className="flex items-center gap-2 py-1">
  <svg ...ícone de documento... />
  <span className="text-[13px] truncate max-w-[180px]">
    {message.content || "Documento"}
  </span>
</div>
```

- `message.content` conterá o nome do arquivo (salvo no DB no passo anterior).
- Se `content` estiver vazio (mensagens recebidas sem nome), exibir "Documento".

---

## Tipos de documento Meta-suportados

| Formato | MIME |
|---------|------|
| PDF | application/pdf |
| Word | application/msword, .docx |
| Excel | application/vnd.ms-excel, .xlsx |
| PowerPoint | application/vnd.ms-powerpoint, .pptx |
| Texto | text/plain |

Qualquer outro MIME não-áudio/não-imagem também pode ser enviado — a Meta rejeita o que não suporta, e o erro já é tratado no `catch` existente.

---

## Tratamento de erros

- Arquivo > 100MB: `alert('Arquivo muito grande. Máximo 100MB para documentos.')` no `handleFileSelect`.
- Falha no upload Meta: comportamento existente (alert com `data.error`).
- Provider não-Meta: o backend já retorna 400 com "Envio de mídia disponível apenas para Meta Cloud".

---

## O que NÃO muda

- Layout do input (nenhum botão novo).
- Fluxo de gravação de áudio.
- Fluxo de envio de imagem.
- Lógica de janela de 24h / template dispatch.
- Evolution API.

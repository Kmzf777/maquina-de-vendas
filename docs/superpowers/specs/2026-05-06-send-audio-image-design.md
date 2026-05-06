# Spec: Envio de Áudio e Imagem pelo Vendedor

**Data:** 2026-05-06
**Status:** Aprovado

---

## Resumo

Adicionar ao chat de conversas a capacidade do vendedor enviar áudio (gravado no browser ou via arquivo) e imagens (via arquivo), usando a Meta Cloud API. O recebimento e renderização de áudio já existe — este spec cobre exclusivamente o caminho de envio.

---

## Escopo

**Incluído:**
- Gravação de áudio diretamente no browser (MediaRecorder)
- Upload de arquivo de áudio ou imagem via seletor de arquivo
- Preview antes do envio (player de áudio ou thumbnail de imagem)
- Envio via Meta Cloud API (upload → media_id → send)
- Renderização de imagens enviadas no message-bubble
- Provider: `meta_cloud` apenas (Evolution não suportado nesta versão)

**Excluído:**
- Vídeos e documentos
- Provider Evolution
- Compressão de imagens no cliente
- Armazenamento no Supabase Storage

---

## Arquitetura

### Fluxo geral

```
Vendedor (browser)
  → clip ou mic button
  → preview (audio player / img thumbnail)
  → confirma
  → POST /api/conversations/[id]/send-media (multipart/form-data)
  → Next.js route: upload para Meta Media API → media_id
  → Next.js route: POST /messages com { type: audio|image, id: media_id }
  → Next.js route: INSERT messages (message_type, media_url=media_id, content="")
  → Supabase Realtime → message-bubble renderiza
```

### Por que Next.js direto (não backend Python)

A rota de texto `/api/conversations/[id]/send` já chama a Meta Graph API diretamente do Next.js usando `provider_config`. Este spec segue o mesmo padrão para manter coerência arquitetural e evitar hop extra frontend → backend → Meta.

---

## UI — chat-view.tsx

### Novos elementos no input bar

O input bar atual tem: `[textarea] [botão enviar]`

Novo layout: `[botão mic] [botão clipe] [textarea] [botão enviar]`

- **Botão mic:** ícone de microfone. Abre fluxo de gravação.
- **Botão clipe:** ícone de clipe. Abre `<input type="file" accept="audio/*,image/*" hidden>`.

Ambos os botões ficam **desabilitados** quando `isInputBlocked` (janela 24h fechada).

### Estados da UI

```
idle          → input bar normal
recording     → mic pulsando (vermelho), timer de duração, botão "parar"
previewing    → preview (audio ou imagem) + botões "Enviar" / "Cancelar"
sending       → botão "Enviar" desabilitado com spinner
```

### Gravação de áudio (MediaRecorder)

1. `navigator.mediaDevices.getUserMedia({ audio: true })`
2. `MediaRecorder` inicia gravação (codec preferido: `audio/webm;codecs=opus` com fallback para `audio/ogg`)
3. Timer de duração visível (segundos)
4. Ao parar: `blob` disponível → estado `previewing`
5. Preview: `<audio controls src={objectURL} />`
6. Confirmar → envia o blob como `File` para `/send-media`

### Upload de arquivo

1. `<input type="file">` onChange → arquivo selecionado → estado `previewing`
2. Preview: `<audio controls>` para `audio/*`, `<img>` para `image/*`
3. Confirmar → envia para `/send-media`

### Mensagem otimista

Durante o envio, adiciona bubble otimista com `message_type` correto e `objectURL` local. Remove ao receber confirmação (igual ao texto).

---

## API Route — /api/conversations/[id]/send-media

**Arquivo:** `frontend/src/app/api/conversations/[id]/send-media/route.ts`

**Método:** `POST` com `Content-Type: multipart/form-data`

**Campos:**
- `file`: Blob/File (obrigatório)

**Lógica:**

1. Parse `params.id` → `conversationId`
2. `formData.get("file")` → valida existência e tamanho (máx 16MB)
3. Busca conversa + canal no Supabase (igual à rota `/send`)
4. Valida `channel.provider === "meta_cloud"`
5. Detecta tipo pela MIME type do arquivo:
   - `audio/*` → `messageType = "audio"`
   - `image/*` → `messageType = "image"`
   - Outros → retorna 400
6. Upload para Meta Media API:
   ```
   POST https://graph.facebook.com/v21.0/{phone_number_id}/media
   Authorization: Bearer {access_token}
   Content-Type: multipart/form-data
   file: <bytes>
   messaging_product: whatsapp
   type: <mimetype>
   ```
   → retorna `{ id: media_id }`
7. Envia mensagem via Meta Graph API:
   ```json
   {
     "messaging_product": "whatsapp",
     "to": "<phone>",
     "type": "audio" | "image",
     "audio": { "id": "<media_id>" }   // ou "image": { "id": "<media_id>" }
   }
   ```
8. Salva no banco:
   ```json
   {
     "lead_id": "...",
     "conversation_id": "...",
     "role": "assistant",
     "content": "",
     "sent_by": "seller",
     "message_type": "audio" | "image",
     "media_url": "<media_id>"
   }
   ```
9. Atualiza `conversations.unread_count = 0` e `last_msg_at`
10. Retorna `{ status: "sent" }`

**Tratamento de erros:**
- Arquivo ausente → 400
- Tipo não suportado → 400
- Provider não é meta_cloud → 400 (mensagem: "Envio de mídia disponível apenas para Meta Cloud")
- Falha no upload Meta → 502 com log do erro

---

## message-bubble.tsx — Renderização de imagem

Adicionar branch para `message_type === "image"`:

```tsx
const isImage = message.message_type === "image";
const mediaSrc = message.media_url
  ? message.media_url.startsWith("http")
    ? message.media_url
    : `/api/media?media_id=${encodeURIComponent(message.media_url)}&conversation_id=${encodeURIComponent(conversationId)}`
  : null;

// No JSX:
{isImage && mediaSrc && (
  <img src={mediaSrc} alt="imagem" className="max-w-[240px] rounded-[4px]" />
)}
```

Para imagens otimistas (durante envio), usa o `objectURL` local passado na mensagem temporária.

---

## Tipos — lib/types.ts

O tipo `Message` já tem `message_type` e `media_url`. Nenhuma mudança necessária de tipos para receber; para otimistas, usamos os campos existentes.

---

## Formatos suportados (Meta Cloud API)

| Tipo   | Formatos aceitos                         | Tamanho máx |
|--------|------------------------------------------|-------------|
| Áudio  | AAC, MP4, MPEG, AMR, OGG (codec OPUS)   | 16 MB       |
| Imagem | JPEG, PNG, WEBP                          | 5 MB        |

---

## Considerações de segurança

- Validar tamanho do arquivo no servidor (não confiar no cliente)
- Validar MIME type com base na extensão + header real do arquivo (não só `file.type`)
- O `access_token` da Meta nunca é exposto ao browser — permanece no Next.js API route

---

## Testes manuais (checklist)

- [ ] Gravar áudio → preview aparece com player → confirmar → bubble aparece → lead recebe no WhatsApp
- [ ] Cancelar gravação → retorna ao estado idle sem enviar
- [ ] Upload de arquivo MP3 → preview → enviar → lead recebe
- [ ] Upload de arquivo JPG → preview de imagem → enviar → lead recebe
- [ ] Upload de arquivo não suportado (PDF) → mensagem de erro no UI
- [ ] Arquivo > 16MB → mensagem de erro antes do upload
- [ ] Janela 24h fechada → botões mic e clipe desabilitados
- [ ] Imagens recebidas (inbound) renderizam corretamente no bubble

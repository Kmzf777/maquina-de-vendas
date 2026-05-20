# Spec: Suporte Completo a Tipos de Mensagem WhatsApp em /conversas

## Contexto

A página `/conversas` não exibe a maioria dos tipos de mensagem do WhatsApp recebidos via Meta Cloud API. Documentos não têm extração de media_url nem botão de download. Sticker, localização, contato e reação não são parseados nem renderizados.

**Escopo:** Meta Cloud API **apenas**. Evolution API está fora de escopo — nenhum arquivo de parser Evolution (parser.py) ou fetchEvolutionMessages é alterado além de adicionar campos opcionais ao dataclass compartilhado IncomingMessage.

---

## Tipos Suportados Após Esta Feature

| Tipo        | `message_type` | `media_url`         | `content`           | `document_name`  | `metadata` JSONB                             |
|-------------|---------------|---------------------|---------------------|------------------|----------------------------------------------|
| text        | —             | —                   | texto               | —                | —                                            |
| image       | image         | media_id (Meta)     | caption ou ""       | —                | —                                            |
| video       | video         | media_id (Meta)     | caption ou ""       | —                | —                                            |
| audio       | audio         | storage_url         | transcript          | —                | —                                            |
| document    | document      | media_id (Meta)     | caption ou ""       | filename.pdf     | —                                            |
| sticker     | sticker       | media_id (Meta)     | ""                  | —                | —                                            |
| location    | location      | —                   | ""                  | —                | `{"lat": X, "lng": Y, "name": Z, "address": A}` |
| contact     | contact       | —                   | ""                  | —                | `{"name": X, "phone": Y, "vcard": Z}`        |
| reaction    | reaction      | —                   | ""                  | —                | `{"emoji": X, "target_wamid": Y}`           |

---

## Mudanças de Schema (DB)

```sql
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS document_name TEXT,
  ADD COLUMN IF NOT EXISTS media_mime    TEXT,
  ADD COLUMN IF NOT EXISTS metadata      JSONB;
```

**Nota:** Esta migration deve ser executada manualmente pelo usuário no Supabase Dashboard antes do deploy.

---

## Arquitetura da Solução

### Fluxo por categoria de tipo

**Tipos com mídia (image, video, document, sticker):**
```
Meta webhook
→ meta_parser.py: extrai media_id → IncomingMessage(type, media_url=media_id, document_name?)
→ buffer/manager.py: placeholder "[type: media_url=MEDIAID]" + opcional filename_b64
→ Redis buffer
→ buffer/processor.py: regex match → message_type + media_url + document_name → save_message
→ DB: messages(message_type, media_url, document_name)
→ Frontend: /api/media?media_id=XXX&conversation_id=YYY (proxy sob demanda)
```

**Tipos estruturados (location, contact, reaction):**
```
Meta webhook
→ meta_parser.py: extrai campos → IncomingMessage(type, metadata={...})
→ buffer/manager.py: placeholder "[type: meta_b64=BASE64_JSON]"
→ Redis buffer
→ buffer/processor.py: decode base64 + json.loads → metadata dict → save_message
→ DB: messages(message_type, metadata JSONB)
→ Frontend: renderiza com base em message.metadata
```

### Por que base64 para metadata?

O Redis buffer combina múltiplas mensagens em texto plano. JSON contém espaços e colchetes que quebram regex simples. Base64 é compacto, não tem espaços e casa com `[A-Za-z0-9+/=]+`.

---

## Arquivos Tocados

| Arquivo | Mudança |
|---------|---------|
| `backend/app/webhook/parser.py` | Adicionar `document_name` e `metadata` ao dataclass IncomingMessage |
| `backend/app/webhook/meta_parser.py` | Capturar `filename` no document; adicionar sticker, location, contacts, reaction |
| `backend/app/buffer/manager.py` | Adicionar "document" e "sticker" ao _MEDIA_TYPES; encoding base64 para meta types |
| `backend/app/buffer/processor.py` | Adicionar patterns/handlers para document, sticker, location, contact, reaction; fix image/video (strip placeholder em vez de texto) |
| `backend/app/conversations/service.py` | Adicionar `document_name`, `media_mime`, `metadata` params ao `save_message` |
| `frontend/src/lib/types.ts` | Adicionar `document_name`, `media_mime`, `metadata` ao interface Message |
| `frontend/src/app/api/media/route.ts` | Suporte a `?download=1&filename=xxx` para Content-Disposition attachment |
| `frontend/src/components/conversas/message-bubble.tsx` | Renderers: document com download, sticker, location, contact, reaction |

---

## Design dos Renderers (Frontend)

### Document
Ícone de arquivo (variante por mime: PDF vermelho, DOCX azul, XLSX verde, genérico cinza) + nome do arquivo + link de download abrindo `/api/media?...&download=1&filename=...` em nova aba.

### Sticker
`<img>` sem fundo de bubble (fundo transparente), mesmas dimensões máximas de imagem.

### Location
Ícone de pin vermelho + nome/endereço em texto + link "Ver no mapa" abrindo `https://maps.google.com/?q=LAT,LNG`.

### Contact
Ícone de pessoa + nome em negrito + telefone + (se vCard disponível) botão "Baixar contato" para download do .vcf.

### Reaction
Bubble pequeno com emoji + label "Reagiu" (sem media, sem timestamp separado).

---

## Decisões de Design

- **Sem storage para documentos/imagens/vídeos/stickers:** apenas `media_id` no banco; proxy `/api/media` busca sob demanda. Áudio mantém storage permanente (necessário para transcrição).
- **document_name separado de content:** preserve o caption sem sobrescrever o nome do arquivo.
- **Evolution ignorado em tudo:** parser.py recebe apenas 2 campos opcionais no dataclass; nenhuma lógica Evolution é alterada.
- **Sem enquetes (poll):** tipo raro, complexo, sem caso de uso identificado. Fora de escopo.

---

## Critérios de Aceitação

- [ ] PDFs e outros documentos exibem ícone, nome do arquivo e botão de download funcional
- [ ] Stickers aparecem como imagem sem fundo de bubble
- [ ] Localização mostra endereço + link clicável para Google Maps
- [ ] Contato mostra nome e telefone; botão "Baixar contato" presente quando vCard disponível
- [ ] Reação exibe emoji com label "Reagiu"
- [ ] Tipos já funcionais (texto, áudio, imagem, vídeo) continuam sem regressão
- [ ] TypeScript compila sem erros
- [ ] Python syntax check passa (`ast.parse`) em todos os arquivos alterados

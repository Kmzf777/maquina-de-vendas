# Spec: Visualização de Imagens e Vídeos em /conversas

## Contexto

Na página `/conversas`, mensagens de imagem e vídeo enviadas pelos leads via WhatsApp Cloud API (Meta) não são exibidas. O problema tem duas causas distintas:

1. **Imagens:** O `_resolve_media` no processor baixa a imagem, descreve com Gemini, mas nunca define `message_type` nem `media_url` — a mensagem é salva como texto puro.
2. **Vídeos:** Nenhum padrão de vídeo existe em `_resolve_media` — o placeholder `[video: media_url=<id>]` é salvo literalmente no banco.

## Decisões de Design

- **Sem storage:** Nenhuma mídia é armazenada permanentemente. Apenas o `media_id` da Meta é salvo no banco.
- **Sem descrição por AI:** Imagens não são mais baixadas nem descritas. Apenas o `media_id` é extraído.
- **Proxy sob demanda:** O proxy existente em `/api/media` serve qualquer tipo de mídia da Meta Graph API. Funciona sem alterações para imagens e vídeos.
- **Vídeo inline:** Player `<video controls>` dentro do bubble de mensagem.

## Fluxo Completo

```
Lead envia imagem/vídeo no WhatsApp
→ Meta envia webhook com media_id no campo `id`
→ meta_parser.py: media_url = image/video.get("id") → media_id
→ buffer/manager.py: text = "[image: media_url=<media_id>]"
→ processor._resolve_media:
    - Extrai media_id do placeholder via regex
    - Define message_type = "image" ou "video"
    - Define storage_url = media_id
    - Substitui placeholder por caption ou string vazia
→ save_message: content=caption, media_url=media_id, message_type=image|video
→ Frontend: mediaSrc = /api/media?media_id=<id>&conversation_id=<id>
→ /api/media: GET /v21.0/<media_id> → {url, mime_type} → stream bytes
→ Browser exibe <img> ou <video controls>
```

## Arquivos Tocados

| Arquivo | Mudança |
|---|---|
| `backend/app/buffer/processor.py` | `_resolve_media`: remover download de imagem, remover descrição Gemini, adicionar image/video sem download |
| `frontend/src/components/conversas/message-bubble.tsx` | Adicionar renderização `<video controls>` para `message_type === "video"` |
| `frontend/src/app/api/media/route.ts` | Corrigir fallback mime-type e comentário |

## Regras de Negócio

- Se a mensagem de imagem/vídeo tiver legenda (caption), ela vai no `content`.
- Se não tiver legenda, `content` fica vazio (string vazia `""`).
- O `media_url` no banco é sempre o `media_id` da Meta (string numérica, ex: `"123456789"`).
- O `message_type` deve ser `"image"` ou `"video"` para que o frontend renderize corretamente.
- Compatibilidade com Evolution API: o padrão `[image: media_url=<url_http>]` já funciona — a URL começa com `http`, o frontend usa direto sem proxy.

## Critérios de Aceitação

- Imagens enviadas por leads aparecem como `<img>` no bubble de mensagem.
- Vídeos enviados por leads aparecem como `<video controls>` no bubble de mensagem.
- Se a imagem falhar ao carregar, exibe ícone de imagem com texto "Imagem".
- Se o vídeo falhar ao carregar, exibe ícone de vídeo com texto "Vídeo".
- Caption da imagem/vídeo aparece como `content` no bubble quando presente.
- Mensagens antigas (sem `media_url`) continuam renderizando como texto sem quebrar.

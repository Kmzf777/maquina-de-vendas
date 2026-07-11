// Placeholder textual para o `content` de mensagens de mídia enviadas pelo vendedor.
// Auditoria 10/07: send-media/route.ts gravava content="" para áudio/imagem — o
// histórico do LLM, o dossiê e o QA no backend ficavam cegos ao que foi enviado
// (ver backend/app/conversations/service.py::describe_media_placeholder, a mesma
// regra do lado servidor). O CRM já renderiza a bolha por message_type/media_url
// (message-bubble.tsx), então esse content não aparece na UI — é só para consumo
// downstream (histórico/dossiê/QA).
export type OutboundMediaType = "audio" | "image" | "video" | "document";

export function describeOutboundMediaContent(
  messageType: OutboundMediaType,
  originalFilename: string
): string {
  switch (messageType) {
    case "audio":
      return "[áudio]";
    case "image":
      return "[imagem]";
    case "video":
      return "[vídeo]";
    case "document":
      return originalFilename;
  }
}

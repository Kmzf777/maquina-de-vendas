/**
 * Texto curto que representa uma mensagem quando ela aparece DENTRO de outra:
 * barra de "respondendo a", bloco de citação, alvo de reação.
 *
 * Regra que importa: um clique em botão NÃO é mídia. Desde
 * backend/app/webhook/meta_parser.py:138-163 o clique chega com
 * `message_type='button'` e o rótulo tocado fica em `content`, então para efeito de
 * preview ele é texto puro. Sem isso, responder a um clique mostra "📎 Mídia" na barra e
 * o vendedor perde justamente a informação que motivou a resposta.
 *
 * Incidente (revisão de 09/09/2026): `isTextualPreview()` nasceu em
 * message-bubble.tsx:80 e foi aplicado nos dois call-sites de lá — QuotedBlock (:94) e
 * ReactionTargetBlock (:137) — mas o TERCEIRO, a barra de resposta em
 * chat-view.tsx:732, ficou com um mapa inline próprio, `message_type !== "text" ? mapa
 * : content`. Além de mostrar "📎 Mídia" para clique, o mapa inline nem tinha
 * 'location'/'contact'. Este módulo é o lugar canônico da regra; message-bubble.tsx
 * ainda carrega a cópia privada dele (fora do escopo desta correção) e deve passar a
 * importar daqui quando for mexido.
 */

const ROTULOS_MIDIA: Record<string, string> = {
  image: "📷 Imagem",
  audio: "🎵 Áudio",
  video: "🎬 Vídeo",
  document: "📄 Documento",
  sticker: "😀 Figurinha",
  location: "📍 Localização",
  contact: "👤 Contato",
};

/** Tipos que, num preview, se leem pelo `content`: texto, clique em botão e legado sem tipo. */
export function isTextualPreview(messageType: string | null | undefined): boolean {
  return !messageType || messageType === "text" || messageType === "button";
}

export function mediaPreviewLabel(messageType: string | null | undefined): string {
  return (messageType && ROTULOS_MIDIA[messageType]) ?? "📎 Mídia";
}

/** Linha única de preview de uma mensagem citada/alvo. */
export function previewText(message: {
  message_type?: string | null;
  content?: string | null;
}): string {
  return isTextualPreview(message.message_type)
    ? message.content ?? ""
    : mediaPreviewLabel(message.message_type);
}

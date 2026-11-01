/**
 * Link de download e tipo de prévia de um anexo do chat (tela Conversas).
 *
 * `media_url` chega em três formatos:
 * - URL do Supabase Storage (https://…): o Storage responde `?download=<nome>` com
 *   Content-Disposition: attachment. O atributo `download` do <a> não vale cross-origin.
 * - `/api/media?media_id=…` (media_id legado da Meta): o proxy aceita `download=1&filename=`.
 * - `blob:` (mensagem recém-enviada): o atributo `download` do <a> resolve.
 */
export type MediaKind = "image" | "video" | "audio" | "document";

const DEFAULT_NAMES: Record<MediaKind, string> = {
  image: "imagem.jpg",
  video: "video.mp4",
  audio: "audio.ogg",
  document: "documento",
};

export function mediaFileName(kind: MediaKind, name?: string | null): string {
  const trimmed = name?.trim();
  return trimmed ? trimmed : DEFAULT_NAMES[kind];
}

export function mediaDownloadHref(src: string, fileName: string): string {
  if (src.startsWith("blob:")) return src;
  if (src.startsWith("http")) {
    const url = new URL(src);
    url.searchParams.set("download", fileName);
    return url.toString();
  }
  const url = new URL(src, "http://x");
  url.searchParams.set("download", "1");
  url.searchParams.set("filename", fileName);
  return url.pathname + url.search;
}

/** PDF abre no visualizador do navegador; sem nome conta como PDF (272 de 275 na base são). */
export function documentPreviewKind(name?: string | null): "pdf" | "file" {
  const trimmed = name?.trim();
  if (!trimmed) return "pdf";
  return /\.pdf$/i.test(trimmed) ? "pdf" : "file";
}

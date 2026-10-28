// Cartão da1f51a7 (27/10/2026). Mídia que não volta mais:
// - `metadata.media_expired`: apagada pela rotação de 180 dias (backend/app/media_retention);
// - media_id legado da Meta (sem cópia no Storage) com mais de 7 dias — a Meta apaga em
//   ~5-7 dias (medido em 27/10: 23-24/10 abriam, ≤19/10 davam 400).
export const META_MEDIA_TTL_DAYS = 7;

type MediaLike = {
  media_url?: string | null;
  metadata?: unknown;
  created_at?: string | null;
};

export function isMediaExpired(m: MediaLike, now: Date = new Date()): boolean {
  const md = m.metadata as { media_expired?: unknown } | null | undefined;
  if (md && md.media_expired === true) return true;
  const url = m.media_url;
  if (!url || url.startsWith("http") || url.startsWith("blob:")) return false;
  if (!m.created_at) return false;
  const idadeMs = now.getTime() - new Date(m.created_at).getTime();
  return idadeMs > META_MEDIA_TTL_DAYS * 86400000;
}

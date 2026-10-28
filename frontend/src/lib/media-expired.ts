// Cartão da1f51a7 (27/10/2026). Mídia que não volta mais:
// - `metadata.media_expired`: apagada pela rotação de 180 dias (backend/app/media_retention);
// - media_id da Meta (sem cópia no Storage) velho demais:
//   * mídia que o CLIENTE mandou: a Meta apaga em ~5-7 dias (medido em 27/10: 23-24/10
//     abriam, ≤19/10 davam 400) → 7 dias;
//   * mídia enviada por nós (vendedor/robô) que caiu no fallback media_id do send-media
//     (`storageUrl ?? mediaId`): a Meta guarda ~30 dias → 30 dias.
export const META_MEDIA_TTL_DAYS = 7;
export const META_SENT_MEDIA_TTL_DAYS = 30;

type MediaLike = {
  media_url?: string | null;
  metadata?: unknown;
  created_at?: string | null;
  role?: string | null;
  sent_by?: string | null;
};

export function isMediaExpired(m: MediaLike, now: Date = new Date()): boolean {
  const md = m.metadata as { media_expired?: unknown } | null | undefined;
  if (md && md.media_expired === true) return true;
  const url = m.media_url;
  if (!url || url.startsWith("http") || url.startsWith("blob:")) return false;
  if (!m.created_at) return false;
  const idadeMs = now.getTime() - new Date(m.created_at).getTime();
  const doCliente = m.sent_by === "user" || m.role === "user";
  const ttlDias = doCliente ? META_MEDIA_TTL_DAYS : META_SENT_MEDIA_TTL_DAYS;
  return idadeMs > ttlDias * 86400000;
}

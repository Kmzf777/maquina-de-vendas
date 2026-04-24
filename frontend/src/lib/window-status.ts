export type WindowStatus = "open" | "expiring" | "closed" | "n/a";

export function getWindowStatus(
  lastCustomerMessageAt: string | null,
  provider: string | null | undefined
): WindowStatus {
  if (provider !== "meta_cloud") return "n/a";
  if (!lastCustomerMessageAt) return "closed";
  const deltaHours = (Date.now() - new Date(lastCustomerMessageAt).getTime()) / (1000 * 60 * 60);
  if (deltaHours < 22) return "open";
  if (deltaHours < 24) return "expiring";
  return "closed";
}

export function windowExpiresInMs(lastCustomerMessageAt: string): number {
  const expiresAt = new Date(lastCustomerMessageAt).getTime() + 24 * 60 * 60 * 1000;
  return Math.max(0, expiresAt - Date.now());
}

export function formatTimeRemaining(ms: number): string {
  const totalMinutes = Math.floor(ms / (1000 * 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours}h ${minutes}min`;
  return `${minutes}min`;
}

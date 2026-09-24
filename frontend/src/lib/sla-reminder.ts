import type { ActiveConversation } from "@/lib/active-conversation";

/**
 * Limite do popup de SLA do vendedor, em minutos de atendimento. É fixo e
 * separado da meta configurável de "em atraso" (sla_settings.target_minutes).
 */
export const SLA_REMINDER_MINUTES = 40;

export interface ReminderCandidate {
  conversationId: string;
  leadId: string;
  elapsedMinutes: number;
}

/**
 * Fila do popup: leads acima do limite, sem os dispensados nesta página e sem a
 * conversa que o vendedor já está com aberta. A maior espera vem primeiro.
 */
export function buildReminderQueue<T extends ReminderCandidate>(
  leads: readonly T[],
  dismissed: ReadonlySet<string>,
  active: ActiveConversation,
): T[] {
  return leads
    .filter((l) => l.elapsedMinutes > SLA_REMINDER_MINUTES)
    .filter((l) => !dismissed.has(l.conversationId))
    .filter((l) => l.conversationId !== active.conversationId && l.leadId !== active.leadId)
    .sort((a, b) => b.elapsedMinutes - a.elapsedMinutes);
}

/** Minuto do dia -> "10h" / "10h30". */
export function formatWindowHour(minuteOfDay: number): string {
  const h = Math.floor(minuteOfDay / 60);
  const m = minuteOfDay % 60;
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, "0")}`;
}

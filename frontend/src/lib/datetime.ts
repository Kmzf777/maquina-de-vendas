import {
  differenceInCalendarDays,
  differenceInMinutes,
  format,
  isToday,
  isYesterday,
  parseISO,
} from "date-fns";
import { ptBR } from "date-fns/locale";

const safeParse = (iso: string): Date | null => {
  try {
    const d = parseISO(iso);
    if (isNaN(d.getTime())) return null;
    return d;
  } catch {
    return null;
  }
};

/**
 * Para timestamps em cards da lista de conversas.
 * Regras: <1min "agora"; <60min "Nmin"; mesmo dia "HH:mm"; ontem "Ontem";
 * <7d nome curto do dia; >7d "dd/MM/yyyy".
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";

  const now = new Date();
  const minutes = differenceInMinutes(now, d);

  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes}min`;
  if (isToday(d)) return format(d, "HH:mm");
  if (isYesterday(d)) return "Ontem";

  const days = differenceInCalendarDays(now, d);
  if (days >= 0 && days < 7) return format(d, "EEE", { locale: ptBR });

  return format(d, "dd/MM/yyyy", { locale: ptBR });
}

/**
 * Para timestamps em bolhas de mensagem. Sempre HH:mm.
 */
export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";
  return format(d, "HH:mm");
}

/**
 * Para separadores de dia no MessageList.
 * Hoje / Ontem / nome do dia (<7d) / "dd 'de' MMMM" / com ano se diferente.
 */
export function formatDayLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";

  if (isToday(d)) return "Hoje";
  if (isYesterday(d)) return "Ontem";

  const now = new Date();
  const days = differenceInCalendarDays(now, d);
  if (days >= 0 && days < 7) return format(d, "EEEE", { locale: ptBR });

  const sameYear = d.getFullYear() === now.getFullYear();
  return sameYear
    ? format(d, "dd 'de' MMMM", { locale: ptBR })
    : format(d, "dd 'de' MMMM 'de' yyyy", { locale: ptBR });
}

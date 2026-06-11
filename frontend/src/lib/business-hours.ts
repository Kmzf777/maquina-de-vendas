/**
 * Utilitário de horas comerciais — America/Sao_Paulo
 *
 * Janela: 10h00–16h00, segunda a sexta (16h00 não incluído).
 * Implementação usa apenas Intl.DateTimeFormat (sem bibliotecas externas).
 *
 * Caso canônico:
 *   from = sexta 15h55 SP → to = segunda 10h10 SP → 15 minutos
 *   (5 min de sexta 15h55→16h00 + 10 min de segunda 10h00→10h10)
 */

const TZ = "America/Sao_Paulo";

// Janela comercial: [início, fim) em minutos desde meia-noite
const BIZ_START_MIN = 10 * 60; // 10h00 = 600
const BIZ_END_MIN = 16 * 60; // 16h00 = 960

export interface BusinessWindow {
  startMin: number;           // minutos desde meia-noite (default 600 = 10h)
  endMin: number;             // default 960 = 16h
  weekdays: Set<number>;      // 0=dom..6=sáb (default seg-sex)
  excludedDates: Set<string>; // 'YYYY-MM-DD' em SP -> 0 min
}

export const DEFAULT_WINDOW: BusinessWindow = {
  startMin: BIZ_START_MIN,
  endMin: BIZ_END_MIN,
  weekdays: new Set([1, 2, 3, 4, 5]),
  excludedDates: new Set<string>(),
};

/** Data SP em 'YYYY-MM-DD' (para casar com excludedDates). */
export function spDateString(date: Date): string {
  const p = tzParts(date);
  const mm = String(p.month).padStart(2, "0");
  const dd = String(p.day).padStart(2, "0");
  return `${p.year}-${mm}-${dd}`;
}

// Offset fixo America/Sao_Paulo: UTC-3 (horário de verão abolido desde 2019)
const SP_OFFSET_MS = 3 * 60 * 60 * 1000;

interface TZParts {
  year: number;
  month: number; // 1–12
  day: number; // 1–31
  hour: number; // 0–23
  minute: number; // 0–59
  weekday: number; // 0=dom, 1=seg, …, 6=sáb
}

// Mapeamento weekday pt-BR abreviado → índice JS (0=dom…6=sáb)
const WEEKDAY_MAP: Record<string, number> = {
  dom: 0, "dom.": 0,
  seg: 1, "seg.": 1,
  ter: 2, "ter.": 2,
  qua: 3, "qua.": 3,
  qui: 4, "qui.": 4,
  sex: 5, "sex.": 5,
  sáb: 6, "sáb.": 6,
  sab: 6, "sab.": 6,
};

/** Extrai partes de data/hora no fuso America/Sao_Paulo via Intl.DateTimeFormat */
function tzParts(date: Date): TZParts {
  const fmt = new Intl.DateTimeFormat("pt-BR", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
    hour12: false,
  });

  const parts = fmt.formatToParts(date);
  const get = (type: string) =>
    parseInt(parts.find((p) => p.type === type)?.value ?? "0", 10);

  const weekdayStr =
    parts.find((p) => p.type === "weekday")?.value?.toLowerCase().trim() ?? "";

  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour: get("hour"),
    minute: get("minute"),
    weekday: WEEKDAY_MAP[weekdayStr] ?? -1,
  };
}

/** true se weekday (0=dom…6=sáb) é dia útil (seg–sex) */
function isWeekday(weekday: number): boolean {
  return weekday >= 1 && weekday <= 5;
}

/**
 * Retorna o timestamp UTC correspondente à meia-noite (00:00:00) de um dia
 * calendário em America/Sao_Paulo (offset fixo UTC-3).
 */
function midnightSPtoUTC(year: number, month: number, day: number): Date {
  // UTC-3: meia-noite local = 03:00 UTC
  return new Date(Date.UTC(year, month - 1, day, 3, 0, 0));
}

/**
 * Retorna os minutos desde meia-noite (hora local SP) para um Date.
 * Usa tzParts para leitura correta no fuso.
 */
function localMinutesOfDay(date: Date): number {
  const p = tzParts(date);
  return p.hour * 60 + p.minute;
}

/**
 * Minutos comerciais no segmento [intervalStart, intervalEnd) para um dia.
 * Usa timestamps UTC da janela comercial para evitar ambiguidade de meia-noite.
 * dayMidnightUTC: resultado de midnightSPtoUTC para o dia em questão.
 */
function bizMinutesInSegment(
  intervalStart: Date,
  intervalEnd: Date,
  weekday: number,
  dayMidnightUTC: Date,
  win: BusinessWindow,
  dateStr: string
): number {
  if (!win.weekdays.has(weekday)) return 0;
  if (win.excludedDates.has(dateStr)) return 0;

  const bizStart = new Date(dayMidnightUTC.getTime() + win.startMin * 60_000);
  const bizEnd   = new Date(dayMidnightUTC.getTime() + win.endMin   * 60_000);

  const effectiveStart = intervalStart > bizStart ? intervalStart : bizStart;
  const effectiveEnd   = intervalEnd   < bizEnd   ? intervalEnd   : bizEnd;

  return Math.max(0, (effectiveEnd.getTime() - effectiveStart.getTime()) / 60_000);
}

/**
 * Minutos comerciais entre dois timestamps.
 *
 * Segmenta o intervalo [from, to) em dias calendário SP e acumula a
 * interseção de cada segmento com a janela 10h–16h seg–sex.
 */
export function businessMinutesBetween(
  from: Date,
  to: Date,
  win: BusinessWindow = DEFAULT_WINDOW
): number {
  if (from >= to) return 0;

  let total = 0;

  const startParts = tzParts(from);
  let year  = startParts.year;
  let month = startParts.month;
  let day   = startParts.day;

  let segStart = from;

  while (segStart < to) {
    const dayMidnight  = midnightSPtoUTC(year, month, day);
    const nextMidnight = new Date(dayMidnight.getTime() + 24 * 60 * 60 * 1000);

    const segEnd = to < nextMidnight ? to : nextMidnight;

    const parts = tzParts(segStart);
    const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    total += bizMinutesInSegment(segStart, segEnd, parts.weekday, dayMidnight, win, dateStr);

    segStart = nextMidnight;
    if (segStart >= to) break;

    const nextParts = tzParts(segStart);
    year  = nextParts.year;
    month = nextParts.month;
    day   = nextParts.day;
  }

  return total;
}

/**
 * Minutos comerciais acumulados desde `from` até agora.
 */
export function businessMinutesElapsed(
  from: Date,
  win: BusinessWindow = DEFAULT_WINDOW
): number {
  return businessMinutesBetween(from, new Date(), win);
}

/**
 * Retorna true se o momento (padrão: agora) está dentro da janela comercial.
 * Janela: 10h00 (inclusive) – 16h00 (exclusive), segunda a sexta, SP.
 */
export function isInBusinessHours(date?: Date): boolean {
  const d = date ?? new Date();
  const p = tzParts(d);
  if (!isWeekday(p.weekday)) return false;
  const mins = p.hour * 60 + p.minute;
  return mins >= BIZ_START_MIN && mins < BIZ_END_MIN;
}

/**
 * Formata minutos como "12min" ou "1h23m" (sem espaço).
 * Exemplos: 12 → "12min", 60 → "1h", 83 → "1h23m"
 */
export function formatBusinessDuration(minutes: number): string {
  const r = Math.round(minutes);
  if (r < 60) return `${r}min`;
  const h = Math.floor(r / 60);
  const m = r % 60;
  return m === 0 ? `${h}h` : `${h}h${m}m`;
}

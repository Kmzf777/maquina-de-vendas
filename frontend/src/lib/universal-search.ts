export type SearchTab = "all" | "leads" | "deals" | "sales" | "conversations";

const VALID_TABS: SearchTab[] = ["all", "leads", "deals", "sales", "conversations"];

export interface ParsedSearchParams {
  q: string;
  tab: SearchTab;
  dateFrom: string | null;
  dateTo: string | null;
  pipelineId: string | null;
  stageId: string | null;
  leadStage: string | null;
  docsOnly: boolean;
  page: number;
}

/** Parses and validates the /api/search query string. Unknown/invalid `tab` falls back to "all". */
export function parseSearchParams(searchParams: URLSearchParams): ParsedSearchParams {
  const rawTab = searchParams.get("tab") ?? "all";
  const tab = (VALID_TABS as string[]).includes(rawTab) ? (rawTab as SearchTab) : "all";
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  return {
    q: (searchParams.get("q") || "").trim(),
    tab,
    dateFrom: searchParams.get("date_from") || null,
    dateTo: searchParams.get("date_to") || null,
    pipelineId: searchParams.get("pipeline_id") || null,
    stageId: searchParams.get("stage_id") || null,
    leadStage: searchParams.get("lead_stage") || null,
    docsOnly: searchParams.get("docs_only") === "true",
    page,
  };
}

/** Page size por aba: preview pequeno (5) na aba "Tudo", página cheia (20) numa aba específica. */
export function limitForTab(tab: SearchTab): number {
  return tab === "all" ? 5 : 20;
}

/** OFFSET (0-indexed) do Postgres a partir de uma página 1-indexed. */
export function offsetFor(page: number, limit: number): number {
  return Math.max(0, (page - 1) * limit);
}

/** Data yyyy-mm-dd -> timestamp UTC de início do dia (p/ filtro `>=`). Timestamps completos passam direto. */
export function startOfDayIso(date: string): string {
  return date.length === 10 ? `${date}T00:00:00.000Z` : date;
}

/** Data yyyy-mm-dd -> timestamp UTC de fim do dia (p/ filtro `<=`). Timestamps completos passam direto. */
export function endOfDayIso(date: string): string {
  return date.length === 10 ? `${date}T23:59:59.999Z` : date;
}

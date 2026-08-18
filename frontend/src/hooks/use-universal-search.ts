"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { debounce } from "@/lib/debounce";
import type { SearchTab } from "@/lib/universal-search";
import type {
  LeadSearchResult,
  DealSearchResult,
  SaleSearchResult,
  ConversationSearchResult,
} from "@/lib/types";

export interface UniversalSearchFilters {
  dateFrom: string;
  dateTo: string;
  pipelineId: string;
  stageId: string;
  leadStage: string;
  docsOnly: boolean;
}

export const EMPTY_FILTERS: UniversalSearchFilters = {
  dateFrom: "",
  dateTo: "",
  pipelineId: "",
  stageId: "",
  leadStage: "",
  docsOnly: false,
};

interface EntityResult<T> {
  data: T[];
  count: number;
}

export interface UniversalSearchResults {
  leads: EntityResult<LeadSearchResult>;
  deals: EntityResult<DealSearchResult>;
  sales: EntityResult<SaleSearchResult>;
  conversations: EntityResult<ConversationSearchResult>;
}

export const EMPTY_RESULTS: UniversalSearchResults = {
  leads: { data: [], count: 0 },
  deals: { data: [], count: 0 },
  sales: { data: [], count: 0 },
  conversations: { data: [], count: 0 },
};

/** Mínimo de caracteres para disparar a busca (mesma regra da rota `/api/search`). */
export const MIN_QUERY_LEN = 2;

/**
 * Contagem total da entidade da aba. `null` na aba "all", que é um preview das
 * quatro entidades e não tem uma contagem única (nem paginação).
 */
export function countForTab(results: UniversalSearchResults, tab: SearchTab): number | null {
  return tab === "all" ? null : results[tab].count;
}

/** True quando nenhuma das quatro entidades trouxe linhas (nada para exibir). */
export function hasAnyResults(results: UniversalSearchResults): boolean {
  return (
    results.leads.data.length > 0 ||
    results.deals.data.length > 0 ||
    results.sales.data.length > 0 ||
    results.conversations.data.length > 0
  );
}

/**
 * Busca ao vivo com debounce (400ms) da página `/busca`. Mínimo 2 caracteres —
 * abaixo disso limpa os resultados sem chamar a API.
 *
 * Os resultados anteriores são mantidos em estado durante um novo carregamento e
 * também quando a chamada falha: a UI dá o feedback de loading/erro por cima da
 * lista, nunca esvaziando-a silenciosamente.
 *
 * Respostas fora de ordem são descartadas via contador de geração (mesmo padrão de
 * `use-realtime-deals.ts`): só a resposta da última chamada disparada aplica estado.
 */
export function useUniversalSearch(
  query: string,
  tab: SearchTab,
  filters: UniversalSearchFilters,
  page: number,
) {
  const [results, setResults] = useState<UniversalSearchResults>(EMPTY_RESULTS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const runSearch = useMemo(
    () =>
      debounce(
        async (q: string, t: SearchTab, f: UniversalSearchFilters, p: number) => {
          const generation = ++generationRef.current;

          if (q.trim().length < MIN_QUERY_LEN) {
            setResults(EMPTY_RESULTS);
            setLoading(false);
            setError(null);
            return;
          }

          setLoading(true);

          const params = new URLSearchParams({ q: q.trim(), tab: t, page: String(p) });
          if (f.dateFrom) params.set("date_from", f.dateFrom);
          if (f.dateTo) params.set("date_to", f.dateTo);
          if (f.pipelineId) params.set("pipeline_id", f.pipelineId);
          if (f.stageId) params.set("stage_id", f.stageId);
          if (f.leadStage) params.set("lead_stage", f.leadStage);
          // A rota faz comparação estrita com a string "true".
          if (f.docsOnly) params.set("docs_only", "true");

          try {
            const res = await fetch(`/api/search?${params}`);
            if (generation !== generationRef.current) return;
            if (!res.ok) {
              const body = await res.json().catch(() => ({}));
              if (generation !== generationRef.current) return;
              setError(body.error || "Erro ao buscar.");
              return;
            }
            const data = (await res.json()) as UniversalSearchResults;
            if (generation !== generationRef.current) return;
            setResults(data);
            setError(null);
          } catch {
            if (generation !== generationRef.current) return;
            setError("Erro ao buscar.");
          } finally {
            if (generation === generationRef.current) setLoading(false);
          }
        },
        400,
      ),
    [],
  );

  useEffect(() => {
    runSearch(query, tab, filters, page);
    return () => runSearch.cancel();
  }, [query, tab, filters, page, runSearch]);

  return { results, loading, error };
}

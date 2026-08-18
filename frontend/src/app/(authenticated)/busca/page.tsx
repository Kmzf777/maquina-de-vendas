"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import {
  useUniversalSearch,
  countForTab,
  hasAnyResults,
  EMPTY_FILTERS,
  MIN_QUERY_LEN,
  type UniversalSearchFilters,
} from "@/hooks/use-universal-search";
import { SearchTabs } from "@/components/search/search-tabs";
import { SearchFiltersBar } from "@/components/search/search-filters-bar";
import { SearchResults } from "@/components/search/search-results";
import { limitForTab, type SearchTab } from "@/lib/universal-search";

export default function BuscaPage() {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<SearchTab>("all");
  const [filters, setFilters] = useState<UniversalSearchFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);

  const { results, loading, error } = useUniversalSearch(query, tab, filters, page);

  // Qualquer mudança de consulta/aba/filtro reinicia a paginação: o offset antigo
  // não faz sentido num conjunto de resultados diferente.
  function handleQueryChange(next: string) {
    setQuery(next);
    setPage(1);
  }

  function handleTabChange(next: SearchTab) {
    setTab(next);
    setPage(1);
  }

  function handleFiltersChange(next: UniversalSearchFilters) {
    setFilters(next);
    setPage(1);
  }

  const tooShort = query.trim().length < MIN_QUERY_LEN;
  const hasResults = hasAnyResults(results);
  // Só a primeira busca (sem nada na tela) mostra skeleton; as seguintes mantêm
  // a lista anterior visível para não piscar a cada tecla digitada.
  const firstLoad = loading && !hasResults;

  // A aba "Tudo" é um preview de 5 por entidade, não uma lista paginada.
  const activeCount = countForTab(results, tab);
  const totalPages = activeCount === null ? 0 : Math.ceil(activeCount / limitForTab(tab));

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-4 md:px-8 py-3 md:py-5 flex-shrink-0">
        <h1
          style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }}
          className="text-[24px] md:text-[32px] font-normal text-[#111111]"
        >
          Busca
        </h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Leads, deals, vendas e conversas em um só lugar</p>
        <div className="relative mt-3">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[#7b7b78] pointer-events-none"
          />
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Buscar leads, deals, vendas, conversas..."
            className="w-full bg-white border border-[#dedbd6] rounded-[6px] pl-9 pr-3.5 py-2.5 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
          />
        </div>
      </div>

      <div className="px-4 md:px-8 flex-shrink-0 bg-white">
        <SearchTabs active={tab} onChange={handleTabChange} results={results} />
        <SearchFiltersBar tab={tab} filters={filters} onChange={handleFiltersChange} />
      </div>

      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-2">
        {tooShort ? (
          <div className="py-12 text-center">
            <p className="text-[14px] text-[#7b7b78]">Digite ao menos 2 caracteres para buscar.</p>
          </div>
        ) : (
          <>
            {/* Erro nunca esvazia a tela: fica por cima do último resultado bom. */}
            {error && (
              <div className="mt-2 mb-1 px-3 py-2 border border-[#c41c1c]/30 bg-[#c41c1c]/5 rounded-[6px]">
                <p className="text-[13px] text-[#c41c1c]">{error}</p>
              </div>
            )}

            {loading && !firstLoad && (
              <p className="px-3 pt-3 text-[12px] text-[#7b7b78]">Buscando...</p>
            )}

            {firstLoad ? (
              <div className="space-y-2 py-4">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-12 bg-[#dedbd6]/30 rounded-[6px] animate-pulse" />
                ))}
              </div>
            ) : (
              <div className={`transition-opacity ${loading ? "opacity-60" : ""}`}>
                <SearchResults tab={tab} results={results} onTabChange={handleTabChange} />

                {activeCount !== null && totalPages > 1 && (
                  <div className="flex items-center justify-between pt-4">
                    <p className="text-[12px] text-[#7b7b78]">
                      {activeCount} resultados · página {page} de {totalPages}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setPage(page - 1)}
                        disabled={page === 1}
                        className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        Anterior
                      </button>
                      <button
                        onClick={() => setPage(page + 1)}
                        disabled={page >= totalPages}
                        className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        Próxima
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

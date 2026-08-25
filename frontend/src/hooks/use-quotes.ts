"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { Quote } from "@/lib/types";

/**
 * Filtros da tela /orcamento. `createdBy` e o e-mail do vendedor — o mesmo campo
 * que o escopo usa, e por isso ele so restringe: a rota combina este filtro com
 * o escopo por AND.
 */
export interface QuotesFilters {
  from?: string;
  to?: string;
  createdBy?: string;
  status?: string;
  search?: string;
  page?: number;
}

/** Gemeo de `useSales`. Mesma forma de retorno para as duas telas lerem igual. */
export function useQuotes(filters: QuotesFilters = {}) {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  /**
   * Numero da chamada mais recente.
   *
   * Digitar na busca dispara uma requisicao por tecla e nada garante que as
   * respostas voltem na ordem em que sairam — a de "caf" pode chegar depois da
   * de "cafe" e repintar a tabela com o resultado da busca ANTERIOR, que e o
   * defeito mais confuso possivel porque a caixa de texto mostra outra coisa.
   * O ref (e nao um estado) porque o valor precisa ser lido depois do `await`
   * sem participar do ciclo de render.
   */
  const geracao = useRef(0);

  const fetchQuotes = useCallback(async () => {
    const minha = ++geracao.current;
    setLoading(true);
    const params = new URLSearchParams();
    if (filters.from) params.set("from", filters.from);
    if (filters.to) params.set("to", filters.to);
    if (filters.createdBy) params.set("created_by", filters.createdBy);
    if (filters.status) params.set("status", filters.status);
    if (filters.search) params.set("search", filters.search);
    if (filters.page) params.set("page", String(filters.page));
    try {
      const res = await fetch(`/api/quotes?${params}`);
      // Superada por uma chamada mais nova: sai sem tocar em nada, INCLUSIVE em
      // `loading` — quem esta em voo agora e quem vai desliga-lo.
      if (minha !== geracao.current) return;
      if (res.ok) {
        const { data, count: c } = await res.json();
        setQuotes(data ?? []);
        setCount(c ?? 0);
      }
      setLoading(false);
    } catch {
      // Rede fora. Sem isto a promessa rejeitaria sem tratamento e a tela
      // ficaria no esqueleto para sempre, sem dizer que falhou.
      if (minha === geracao.current) setLoading(false);
    }
    // As dependencias sao os CAMPOS, nao o objeto `filters`: a pagina recria o
    // objeto a cada render e depender dele daria um loop de fetch infinito.
  }, [filters.from, filters.to, filters.createdBy, filters.status, filters.search, filters.page]);

  useEffect(() => {
    fetchQuotes();
  }, [fetchQuotes]);

  return { quotes, count, loading, refetch: fetchQuotes };
}

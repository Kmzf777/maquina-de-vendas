"use client";

import { useCallback, useEffect, useState } from "react";
import type { Quote } from "@/lib/types";

/**
 * Orçamentos de um lead — espelho de `use-lead-sales`.
 *
 * Sem inscrição realtime, pela mesma razão que `sales` não tem: a tabela não
 * está na publicação `supabase_realtime`, então o canal ficaria ocioso fingindo
 * que atualiza. Quem muda alguma coisa chama `refetch`.
 *
 * `GET /api/quotes?lead_id=…` já devolve `quote_items` embutido (§5 da spec) —
 * é o mesmo endpoint que a página `/orcamento` consome, com o escopo por
 * vendedor aplicado na rota. O corpo é aceito tanto como array puro quanto como
 * `{data: [...]}` porque as duas formas convivem nas rotas deste projeto, e
 * errar a leitura aqui esvaziaria a lista em silêncio.
 */
export function useLeadQuotes(leadId: string | null | undefined) {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchQuotes = useCallback(async () => {
    if (!leadId) {
      setQuotes([]);
      return;
    }
    setLoading(true);
    const res = await fetch(
      `/api/quotes?lead_id=${encodeURIComponent(leadId)}`,
    ).catch(() => null);
    if (res?.ok) {
      const body = await res.json().catch(() => null);
      setQuotes(Array.isArray(body) ? body : (body?.data ?? []));
    }
    setLoading(false);
  }, [leadId]);

  useEffect(() => {
    fetchQuotes();
  }, [fetchQuotes]);

  return { quotes, loading, refetch: fetchQuotes };
}

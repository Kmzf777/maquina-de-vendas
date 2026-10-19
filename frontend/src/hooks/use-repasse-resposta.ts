"use client";

import { useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { fetchRepasseResposta, type RepasseResposta } from "@/lib/repasse-resposta";

/**
 * Linha da view para UM lead, lida pelo client do browser (RLS do usuário).
 * Erro ou view ausente → `linha: null` (a tela mostra "—"), nunca exceção.
 */
export function useRepasseResposta(leadId: string): { carregando: boolean; linha: RepasseResposta | null } {
  const [res, setRes] = useState<{ leadId: string; linha: RepasseResposta | null } | null>(null);

  useEffect(() => {
    let vivo = true;
    import("@/lib/supabase/client")
      .then(({ createClient }) => fetchRepasseResposta(createClient() as unknown as SupabaseClient, [leadId]))
      .then((mapa) => {
        if (vivo) setRes({ leadId, linha: mapa.get(leadId) ?? null });
      })
      .catch(() => {
        if (vivo) setRes({ leadId, linha: null });
      });
    return () => {
      vivo = false;
    };
  }, [leadId]);

  if (!res || res.leadId !== leadId) return { carregando: true, linha: null };
  return { carregando: false, linha: res.linha };
}

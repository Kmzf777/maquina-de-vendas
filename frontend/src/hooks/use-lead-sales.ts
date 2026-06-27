"use client";

import { useEffect, useState, useCallback } from "react";
import type { Sale } from "@/lib/types";

export function useLeadSales(leadId: string | null | undefined) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchSales = useCallback(async () => {
    if (!leadId) { setSales([]); return; }
    setLoading(true);
    const res = await fetch(`/api/leads/${leadId}/sales`);
    if (res.ok) setSales(await res.json());
    setLoading(false);
  }, [leadId]);

  // `sales` não está na publicação `supabase_realtime`, então a antiga inscrição
  // postgres_changes nunca disparava (canal WebSocket ocioso). Mantemos só o
  // refetch sob demanda; consumidores chamam `refetch` após mutações.
  useEffect(() => {
    fetchSales();
  }, [fetchSales]);

  return { sales, loading, refetch: fetchSales };
}

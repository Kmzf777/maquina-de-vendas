"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Sale } from "@/lib/types";

export function useLeadSales(leadId: string | null | undefined) {
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(false);
  const supabase = useMemo(() => createClient(), []);

  const fetchSales = useCallback(async () => {
    if (!leadId) { setSales([]); return; }
    setLoading(true);
    const res = await fetch(`/api/leads/${leadId}/sales`);
    if (res.ok) setSales(await res.json());
    setLoading(false);
  }, [leadId]);

  useEffect(() => {
    fetchSales();
    if (!leadId) return;
    const channel = supabase
      .channel(`sales-lead-${leadId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "sales", filter: `lead_id=eq.${leadId}` },
        fetchSales
      )
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchSales, leadId, supabase]);

  return { sales, loading, refetch: fetchSales };
}

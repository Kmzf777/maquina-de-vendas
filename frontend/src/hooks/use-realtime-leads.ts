"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Lead } from "@/lib/types";

export function useRealtimeLeads(filter?: { human_control?: boolean }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchLeads = useCallback(async () => {
    const pageSize = 1000;
    const all: Lead[] = [];
    for (let from = 0; ; from += pageSize) {
      let query = supabase
        .from("leads")
        .select("*")
        .order("last_msg_at", { ascending: false, nullsFirst: false })
        .range(from, from + pageSize - 1);

      if (filter?.human_control !== undefined) {
        query = query.eq("human_control", filter.human_control);
      }

      const { data, error } = await query;
      if (error || !data) break;
      all.push(...data);
      if (data.length < pageSize) break;
    }
    setLeads(all);
    setLoading(false);
  }, [filter?.human_control]);

  // `leads` não está na publicação `supabase_realtime`, então a antiga inscrição
  // postgres_changes nunca entregava eventos (canal WebSocket ocioso). A lista já
  // dependia de refetch/mount; mantemos só isso e expomos `refetch` sob demanda.
  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  return { leads, loading, refetch: fetchLeads };
}

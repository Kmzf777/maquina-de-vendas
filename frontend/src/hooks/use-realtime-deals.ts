"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Deal } from "@/lib/types";

export function useRealtimeDeals(pipelineId?: string | null) {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = useMemo(() => createClient(), []);
  const generationRef = useRef(0);

  const fetchDeals = useCallback(async () => {
    const generation = ++generationRef.current;
    let query = supabase
      .from("deals")
      .select("*, leads(id, name, company, phone, nome_fantasia), pipeline_stages(id, label, key, dot_color, order_index, is_protected)")
      .order("updated_at", { ascending: false });
    if (pipelineId) query = query.eq("pipeline_id", pipelineId);
    const { data } = await query;
    if (generation !== generationRef.current) return;
    if (data) setDeals(data);
    setLoading(false);
  }, [pipelineId, supabase]);

  useEffect(() => {
    setLoading(true);
    fetchDeals();
    const channelName = pipelineId ? `deals-changes-${pipelineId}` : "deals-changes-all";
    const channel = supabase
      .channel(channelName)
      .on("postgres_changes", { event: "*", schema: "public", table: "deals" }, fetchDeals)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [fetchDeals, pipelineId, supabase]);

  return { deals, loading };
}

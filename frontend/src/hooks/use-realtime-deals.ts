"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Deal } from "@/lib/types";

export function useRealtimeDeals() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchDeals = useCallback(async () => {
    const { data } = await supabase
      .from("deals")
      .select("*, leads(id, name, company, phone, nome_fantasia)")
      .order("updated_at", { ascending: false });
    if (data) setDeals(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchDeals();

    const channel = supabase
      .channel("deals-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "deals" },
        () => {
          fetchDeals();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchDeals]);

  return { deals, loading };
}

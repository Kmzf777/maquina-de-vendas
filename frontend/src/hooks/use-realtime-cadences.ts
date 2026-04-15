"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Cadence } from "@/lib/types";

export function useRealtimeCadences() {
  const [cadences, setCadences] = useState<Cadence[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchCadences = useCallback(async () => {
    const { data } = await supabase
      .from("cadences")
      .select("*")
      .order("created_at", { ascending: false });
    if (data) setCadences(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchCadences();

    const channel = supabase
      .channel("cadences-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "cadences" },
        () => fetchCadences()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchCadences]);

  return { cadences, loading };
}

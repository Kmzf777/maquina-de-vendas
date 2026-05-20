"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Campaign } from "@/lib/types";

export function useRealtimeCampaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const res = await fetch("/api/campaigns");
    if (res.ok) {
      const json = await res.json();
      setCampaigns(json.data ?? []);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const supabase = createClient();
    const channel = supabase
      .channel("campaigns-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "campaigns" }, load)
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [load]);

  return { campaigns, loading, refresh: load };
}

"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Broadcast } from "@/lib/types";

export function useRealtimeBroadcasts() {
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchBroadcasts = useCallback(async () => {
    const { data } = await supabase
      .from("broadcasts")
      .select("*, cadences(id, name)")
      .order("created_at", { ascending: false });
    if (data) setBroadcasts(data);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchBroadcasts();

    const channel = supabase
      .channel("broadcasts-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "broadcasts" },
        () => fetchBroadcasts()
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchBroadcasts]);

  return { broadcasts, loading };
}

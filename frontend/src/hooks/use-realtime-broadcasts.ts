"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { onResubscribe } from "@/lib/realtime-resync";
import type { Broadcast } from "@/lib/types";

export function useRealtimeBroadcasts() {
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchBroadcasts = useCallback(async () => {
    const { data, error } = await supabase
      .from("broadcasts")
      .select("*")
      .order("created_at", { ascending: false });
    if (error) console.error("[useRealtimeBroadcasts]", error.message);
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
      .subscribe(onResubscribe(fetchBroadcasts));

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchBroadcasts]);

  return { broadcasts, loading };
}

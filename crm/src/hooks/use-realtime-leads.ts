"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Lead } from "@/lib/types";

export function useRealtimeLeads(filter?: { human_control?: boolean }) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchLeads = useCallback(async () => {
    let query = supabase.from("leads").select("*").order("last_msg_at", { ascending: false, nullsFirst: false });

    if (filter?.human_control !== undefined) {
      query = query.eq("human_control", filter.human_control);
    }

    const { data } = await query;
    if (data) setLeads(data);
    setLoading(false);
  }, [filter?.human_control]);

  useEffect(() => {
    fetchLeads();

    const channel = supabase
      .channel("leads-changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "leads" },
        () => {
          fetchLeads();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchLeads]);

  return { leads, loading };
}

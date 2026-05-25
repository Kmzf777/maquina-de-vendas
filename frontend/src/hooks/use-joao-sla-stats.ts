"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  businessMinutesBetween,
  businessMinutesElapsed,
} from "@/lib/business-hours";

const JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd";

export type DateFilter = "1d" | "7d" | "30d" | "all";

interface ConversationRow {
  id: string;
  created_at: string;
  first_seller_response_at: string | null;
  last_seller_response_at: string | null;
  leads: {
    last_customer_message_at: string | null;
  } | null;
}

function getCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const now = new Date();
  const days = filter === "1d" ? 1 : filter === "7d" ? 7 : 30;
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
}

/** Returns today's date string (YYYY-MM-DD) in America/Sao_Paulo */
function todayInSaoPaulo(): string {
  return new Date().toLocaleDateString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

/** Returns the date string (dd/mm/yyyy) for a given timestamp in America/Sao_Paulo */
function dateInSaoPaulo(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

async function fetchAllConversations(
  supabase: ReturnType<typeof createClient>,
  cutoff: Date | null
): Promise<ConversationRow[]> {
  const PAGE_SIZE = 1000;
  const allRows: ConversationRow[] = [];
  let offset = 0;

  while (true) {
    let query = supabase
      .from("conversations")
      .select(
        `id, created_at, first_seller_response_at, last_seller_response_at,
         leads(last_customer_message_at)`
      )
      .eq("channel_id", JOAO_CHANNEL_ID)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE_SIZE - 1);

    if (cutoff) {
      query = query.gte("created_at", cutoff.toISOString());
    }

    const { data, error } = await query;
    if (error) {
      console.error("[useJoaoSlaStats] fetch error:", error);
      break;
    }
    if (!data || data.length === 0) break;

    // Supabase returns `leads` as array from the join; normalise to single object
    const normalised: ConversationRow[] = (data as unknown[]).map((row: unknown) => {
      const r = row as Record<string, unknown>;
      const leadsArr = r.leads as Array<{ last_customer_message_at: string | null }> | null;
      return {
        ...(r as Omit<ConversationRow, "leads">),
        leads: Array.isArray(leadsArr) && leadsArr.length > 0 ? leadsArr[0] : null,
      } as ConversationRow;
    });
    allRows.push(...normalised);

    if (data.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }

  return allRows;
}

function computeStats(rows: ConversationRow[]) {
  const today = todayInSaoPaulo();

  // avgSlaMinutes: only rows with both created_at and first_seller_response_at
  const withFirstResponse = rows.filter((r) => r.first_seller_response_at);
  const slaValues = withFirstResponse.map((r) =>
    businessMinutesBetween(
      new Date(r.created_at),
      new Date(r.first_seller_response_at!)
    )
  );
  const avgSlaMinutes =
    slaValues.length > 0
      ? Math.round(slaValues.reduce((a, b) => a + b, 0) / slaValues.length)
      : null;

  // overdueCount: last message is from customer and elapsed > 20 business minutes
  const overdueCount = rows.filter((r) => {
    const lastCustomer = r.leads?.last_customer_message_at;
    if (!lastCustomer) return false;
    const lastSeller = r.last_seller_response_at;
    // If seller responded after customer, not overdue
    if (lastSeller && lastSeller >= lastCustomer) return false;
    return businessMinutesElapsed(new Date(lastCustomer)) > 20;
  }).length;

  // worstSlaTodayMinutes: max SLA among rows whose first_seller_response_at is today (SP)
  const todayResponseRows = withFirstResponse.filter(
    (r) => dateInSaoPaulo(r.first_seller_response_at!) === today
  );
  const todaySlaValues = todayResponseRows.map((r) =>
    businessMinutesBetween(
      new Date(r.created_at),
      new Date(r.first_seller_response_at!)
    )
  );
  const worstSlaTodayMinutes =
    todaySlaValues.length > 0 ? Math.max(...todaySlaValues) : null;

  return { avgSlaMinutes, overdueCount, worstSlaTodayMinutes };
}

export interface JoaoSlaStats {
  avgSlaMinutes: number | null;
  overdueCount: number;
  worstSlaTodayMinutes: number | null;
  loading: boolean;
}

export function useJoaoSlaStats(filter: DateFilter = "7d"): JoaoSlaStats {
  const [stats, setStats] = useState<Omit<JoaoSlaStats, "loading">>({
    avgSlaMinutes: null,
    overdueCount: 0,
    worstSlaTodayMinutes: null,
  });
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const cutoff = getCutoff(filter);
    const rows = await fetchAllConversations(supabase, cutoff);
    setStats(computeStats(rows));
    setLoading(false);
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const channel = supabase
      .channel("joao-sla-conversations")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "conversations" },
        () => {
          fetchAndCompute();
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchAndCompute]);

  return { ...stats, loading };
}

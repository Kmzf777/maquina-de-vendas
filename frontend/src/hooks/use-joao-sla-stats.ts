"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  businessMinutesBetween,
  businessMinutesElapsed,
} from "@/lib/business-hours";

const JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd";

export type DateFilter = "1d" | "7d" | "30d" | "all";

interface ConvRow {
  id: string;
  created_at: string;
  last_seller_response_at: string | null;
  leads: { last_customer_message_at: string | null } | null;
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

function getCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const days = filter === "1d" ? 1 : filter === "7d" ? 7 : 30;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}


async function fetchConversations(
  supabase: ReturnType<typeof createClient>
): Promise<ConvRow[]> {
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;

  while (true) {
    const { data, error } = await supabase
      .from("conversations")
      .select("id, created_at, last_seller_response_at, leads(last_customer_message_at)")
      .eq("channel_id", JOAO_CHANNEL_ID)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);

    if (error || !data || data.length === 0) break;

    const rows: ConvRow[] = (data as unknown[]).map((r) => {
      const row = r as Record<string, unknown>;
      const leadsArr = row.leads as Array<{ last_customer_message_at: string | null }> | null;
      return {
        ...(row as Omit<ConvRow, "leads">),
        leads: Array.isArray(leadsArr) && leadsArr.length > 0 ? leadsArr[0] : null,
      } as ConvRow;
    });

    all.push(...rows);
    if (data.length < PAGE) break;
    offset += PAGE;
  }

  return all;
}

async function fetchMessages(
  supabase: ReturnType<typeof createClient>,
  convIds: string[]
): Promise<MsgRow[]> {
  if (convIds.length === 0) return [];

  const PAGE = 1000;
  const all: MsgRow[] = [];
  let offset = 0;

  while (true) {
    const { data, error } = await supabase
      .from("messages")
      .select("conversation_id, sent_by, created_at")
      .in("conversation_id", convIds)
      .in("sent_by", ["user", "seller"])
      .order("created_at", { ascending: true })
      .range(offset, offset + PAGE - 1);

    if (error || !data || data.length === 0) break;
    all.push(...(data as MsgRow[]));
    if (data.length < PAGE) break;
    offset += PAGE;
  }

  return all;
}

/**
 * Computa pares (última msg do cliente antes de resposta do vendedor → msg do vendedor).
 * Retorna lista de businessMinutes por par.
 * Também inclui conversas "finalizadas" via last_seller_response_at quando não há
 * mensagem seller após a última msg do cliente.
 */
function computePairs(convs: ConvRow[], msgs: MsgRow[]): number[] {
  // Agrupa mensagens por conversa
  const byConv = new Map<string, MsgRow[]>();
  for (const m of msgs) {
    if (!byConv.has(m.conversation_id)) byConv.set(m.conversation_id, []);
    byConv.get(m.conversation_id)!.push(m);
  }

  const pairs: number[] = [];

  for (const conv of convs) {
    const convMsgs = byConv.get(conv.id) ?? [];
    // convMsgs já estão ordenados por created_at ASC

    let lastUserAt: string | null = null;

    for (const msg of convMsgs) {
      if (msg.sent_by === "user") {
        // Acumula — mantém a última msg do cliente antes da resposta do vendedor
        lastUserAt = msg.created_at;
      } else if (msg.sent_by === "seller" && lastUserAt) {
        const mins = businessMinutesBetween(
          new Date(lastUserAt),
          new Date(msg.created_at)
        );
        if (mins >= 0) pairs.push(mins);
        lastUserAt = null; // ciclo encerrado
      }
    }

    // Se sobrou msg do cliente sem resposta textual, verifica se a conversa
    // foi "finalizada" (last_seller_response_at atualizado via botão Finalizar)
    if (lastUserAt && conv.last_seller_response_at) {
      const lastSeller = conv.last_seller_response_at;
      if (lastSeller > lastUserAt) {
        const mins = businessMinutesBetween(
          new Date(lastUserAt),
          new Date(lastSeller)
        );
        if (mins >= 0) pairs.push(mins);
      }
    }
  }

  return pairs;
}

function computeStats(convs: ConvRow[], msgs: MsgRow[], cutoff: Date | null) {
  // SLA metrics (avg, worst) respect the selected period
  const periodConvs = cutoff
    ? convs.filter((c) => new Date(c.created_at) >= cutoff)
    : convs;
  const pairs = computePairs(periodConvs, msgs);

  const avgSlaMinutes =
    pairs.length > 0
      ? pairs.reduce((a, b) => a + b, 0) / pairs.length
      : null;

  // overdueCount is real-time — all conversations regardless of period
  const overdueCount = convs.filter((conv) => {
    const lastCustomer = conv.leads?.last_customer_message_at;
    if (!lastCustomer) return false;
    const lastSeller = conv.last_seller_response_at;
    if (lastSeller && lastSeller >= lastCustomer) return false;
    return businessMinutesElapsed(new Date(lastCustomer)) > 20;
  }).length;

  const worstSlaMinutes = pairs.length > 0 ? Math.max(...pairs) : null;

  return { avgSlaMinutes, overdueCount, worstSlaMinutes };
}

export interface JoaoSlaStats {
  avgSlaMinutes: number | null;
  overdueCount: number;
  worstSlaMinutes: number | null;
  loading: boolean;
}

export function useJoaoSlaStats(filter: DateFilter = "7d"): JoaoSlaStats {
  const [stats, setStats] = useState<Omit<JoaoSlaStats, "loading">>({
    avgSlaMinutes: null,
    overdueCount: 0,
    worstSlaMinutes: null,
  });
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const cutoff = getCutoff(filter);
    const convs = await fetchConversations(supabase);
    const convIds = convs.map((c) => c.id);
    const msgs = await fetchMessages(supabase, convIds);
    setStats(computeStats(convs, msgs, cutoff));
    setLoading(false);
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const channel = supabase
      .channel("joao-sla-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, fetchAndCompute)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, fetchAndCompute)
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [fetchAndCompute]);

  return { ...stats, loading };
}

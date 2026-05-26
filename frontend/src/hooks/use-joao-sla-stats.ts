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
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

interface OverdueCandidate {
  conversation_id: string;
  last_user_at: string;
}

function getCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const days = filter === "1d" ? 1 : filter === "7d" ? 7 : 30;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}

// Conversas do período para o cálculo dos pares de SLA (avg / pior).
async function fetchConversations(
  supabase: ReturnType<typeof createClient>,
  cutoff: Date | null
): Promise<ConvRow[]> {
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;

  while (true) {
    let q = supabase
      .from("conversations")
      .select("id, created_at, last_seller_response_at")
      .eq("channel_id", JOAO_CHANNEL_ID)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);

    if (cutoff) q = q.gte("created_at", cutoff.toISOString());

    const { data, error } = await q;
    if (error || !data || data.length === 0) break;

    all.push(...(data as ConvRow[]));
    if (data.length < PAGE) break;
    offset += PAGE;
  }

  return all;
}

// Candidatos a "em atraso" computados server-side a partir da tabela messages
// (verdade por conversa) + fallback do botão Finalizar. Retorna last_user_at
// para aplicarmos o filtro de horário comercial no cliente.
async function fetchOverdueCandidates(
  supabase: ReturnType<typeof createClient>
): Promise<OverdueCandidate[]> {
  const { data, error } = await supabase.rpc("get_seller_overdue_candidates", {
    p_channel_id: JOAO_CHANNEL_ID,
  });
  if (error || !data) return [];
  return data as OverdueCandidate[];
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
 */
function computePairs(convs: ConvRow[], msgs: MsgRow[]): number[] {
  const byConv = new Map<string, MsgRow[]>();
  for (const m of msgs) {
    if (!byConv.has(m.conversation_id)) byConv.set(m.conversation_id, []);
    byConv.get(m.conversation_id)!.push(m);
  }

  const pairs: number[] = [];

  for (const conv of convs) {
    const convMsgs = byConv.get(conv.id) ?? [];
    let lastUserAt: string | null = null;

    for (const msg of convMsgs) {
      if (msg.sent_by === "user") {
        lastUserAt = msg.created_at;
      } else if (msg.sent_by === "seller" && lastUserAt) {
        const mins = businessMinutesBetween(
          new Date(lastUserAt),
          new Date(msg.created_at)
        );
        if (mins >= 0) pairs.push(mins);
        lastUserAt = null;
      }
    }

    // Conversa "finalizada" via botão Finalizar
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

function computeStats(
  periodConvs: ConvRow[],
  msgs: MsgRow[],
  overdueCandidates: OverdueCandidate[]
) {
  const pairs = computePairs(periodConvs, msgs);

  const avgSlaMinutes =
    pairs.length > 0
      ? pairs.reduce((a, b) => a + b, 0) / pairs.length
      : null;

  const worstSlaMinutes = pairs.length > 0 ? Math.max(...pairs) : null;

  // 'Em atraso agora': candidatos com última msg do cliente sem resposta há
  // mais de 20 minutos comerciais (tempo decorrido até agora).
  const overdueCount = overdueCandidates.filter(
    (c) => businessMinutesElapsed(new Date(c.last_user_at)) > 20
  ).length;

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
    const [periodConvs, overdueCandidates] = await Promise.all([
      fetchConversations(supabase, cutoff),
      fetchOverdueCandidates(supabase),
    ]);
    const convIds = periodConvs.map((c) => c.id);
    const msgs = await fetchMessages(supabase, convIds);
    setStats(computeStats(periodConvs, msgs, overdueCandidates));
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

    // Recalcula a cada 60s: 'em atraso agora' depende do tempo decorrido,
    // não só de eventos do banco.
    const ticker = setInterval(fetchAndCompute, 60_000);

    return () => {
      supabase.removeChannel(channel);
      clearInterval(ticker);
    };
  }, [fetchAndCompute]);

  return { ...stats, loading };
}

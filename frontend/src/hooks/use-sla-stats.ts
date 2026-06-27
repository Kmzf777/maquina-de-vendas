"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { debounce } from "@/lib/debounce";
import { spDateString, type BusinessWindow } from "@/lib/business-hours";
import {
  collectRounds,
  summarizeRounds,
  type SlaConversation,
  type SellerRounds,
  type SellerSlaResult,
} from "@/lib/sla-rounds";

export type DateFilter = "1d" | "7d" | "30d" | "all";

interface SellerConfigRow {
  user_id: string;
  channel_id: string;
  display_name: string;
  window_start_minute: number;
  window_end_minute: number;
  active_weekdays: number[];
  active: boolean;
}

interface OverrideRow {
  user_id: string | null;
  start_date: string; // 'YYYY-MM-DD'
  end_date: string;
}

interface ConvRow {
  id: string;
  channel_id: string;
  last_seller_response_at: string | null;
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

export interface SlaRow extends SellerSlaResult {
  userId: string;
  displayName: string;
}

export interface SlaTableData {
  rows: SlaRow[];
  total: SellerSlaResult;
  loading: boolean;
}

function getCutoff(filter: DateFilter): Date | null {
  if (filter === "all") return null;
  const days = filter === "1d" ? 1 : filter === "7d" ? 7 : 30;
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}

/** Expande overrides (do vendedor + globais) em datas 'YYYY-MM-DD'. */
function buildExcludedDates(overrides: OverrideRow[], userId: string): Set<string> {
  const out = new Set<string>();
  for (const o of overrides) {
    if (o.user_id !== null && o.user_id !== userId) continue;
    const start = new Date(`${o.start_date}T12:00:00Z`);
    const end = new Date(`${o.end_date}T12:00:00Z`);
    for (let d = start; d <= end; d = new Date(d.getTime() + 86_400_000)) {
      out.add(spDateString(d));
    }
  }
  return out;
}

function windowFor(cfg: SellerConfigRow, overrides: OverrideRow[]): BusinessWindow {
  return {
    startMin: cfg.window_start_minute,
    endMin: cfg.window_end_minute,
    weekdays: new Set(cfg.active_weekdays),
    excludedDates: buildExcludedDates(overrides, cfg.user_id),
  };
}

async function fetchConversations(
  supabase: ReturnType<typeof createClient>,
  channelIds: string[],
  cutoff: Date | null
): Promise<ConvRow[]> {
  if (channelIds.length === 0) return [];
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;
  while (true) {
    let q = supabase
      .from("conversations")
      .select("id, channel_id, last_seller_response_at")
      .in("channel_id", channelIds)
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

async function fetchMessages(
  supabase: ReturnType<typeof createClient>,
  convIds: string[]
): Promise<MsgRow[]> {
  if (convIds.length === 0) return [];
  const PAGE = 1000;
  const all: MsgRow[] = [];
  // chunk de ids para não estourar limites de URL
  const CHUNK = 200;
  for (let i = 0; i < convIds.length; i += CHUNK) {
    const slice = convIds.slice(i, i + CHUNK);
    let offset = 0;
    while (true) {
      const { data, error } = await supabase
        .from("messages")
        .select("conversation_id, sent_by, created_at")
        .in("conversation_id", slice)
        .in("role", ["user", "assistant"])
        .order("created_at", { ascending: true })
        .range(offset, offset + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as MsgRow[]));
      if (data.length < PAGE) break;
      offset += PAGE;
    }
  }
  return all;
}

function groupConversations(convs: ConvRow[], msgs: MsgRow[]): Map<string, SlaConversation[]> {
  const byConv = new Map<string, MsgRow[]>();
  for (const m of msgs) {
    if (!byConv.has(m.conversation_id)) byConv.set(m.conversation_id, []);
    byConv.get(m.conversation_id)!.push(m);
  }
  const byChannel = new Map<string, SlaConversation[]>();
  for (const c of convs) {
    const slaConv: SlaConversation = {
      id: c.id,
      last_seller_response_at: c.last_seller_response_at,
      messages: byConv.get(c.id) ?? [],
    };
    if (!byChannel.has(c.channel_id)) byChannel.set(c.channel_id, []);
    byChannel.get(c.channel_id)!.push(slaConv);
  }
  return byChannel;
}

export function useSlaStats(filter: DateFilter = "7d"): SlaTableData {
  const [rows, setRows] = useState<SlaRow[]>([]);
  const [total, setTotal] = useState<SellerSlaResult>({
    avgMinutes: null,
    overdueCount: 0,
    worstMinutes: null,
  });
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const cutoff = getCutoff(filter);

    const [{ data: cfgData }, { data: ovData }, { data: settingsData }] = await Promise.all([
      supabase.from("sla_seller_config").select("user_id, channel_id, display_name, window_start_minute, window_end_minute, active_weekdays, active").eq("active", true),
      supabase.from("sla_overrides").select("user_id, start_date, end_date"),
      supabase.from("sla_settings").select("target_minutes").eq("id", 1).single(),
    ]);

    const configs = (cfgData ?? []) as SellerConfigRow[];
    const overrides = (ovData ?? []) as OverrideRow[];
    const target = (settingsData?.target_minutes ?? 20) as number;

    const channelIds = configs.map((c) => c.channel_id);
    const convs = await fetchConversations(supabase, channelIds, cutoff);
    const msgs = await fetchMessages(supabase, convs.map((c) => c.id));
    const byChannel = groupConversations(convs, msgs);

    const now = new Date();
    const pooled: SellerRounds = { closed: [], openElapsed: [] };
    const computedRows: SlaRow[] = [];

    for (const cfg of configs) {
      const win = windowFor(cfg, overrides);
      const convsForChannel = byChannel.get(cfg.channel_id) ?? [];
      const rounds = collectRounds(convsForChannel, win, now);
      pooled.closed.push(...rounds.closed);
      pooled.openElapsed.push(...rounds.openElapsed);
      const summary = summarizeRounds(rounds, target);
      computedRows.push({
        userId: cfg.user_id,
        displayName: cfg.display_name || "(sem nome)",
        ...summary,
      });
    }

    computedRows.sort((a, b) => b.overdueCount - a.overdueCount);
    setRows(computedRows);
    setTotal(summarizeRounds(pooled, target));
    setLoading(false);
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const debounced = debounce(fetchAndCompute, 1500);
    const channel = supabase
      .channel("sla-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, debounced)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, debounced)
      .subscribe();

    return () => {
      debounced.cancel();
      supabase.removeChannel(channel);
    };
  }, [fetchAndCompute]);

  return { rows, total, loading };
}

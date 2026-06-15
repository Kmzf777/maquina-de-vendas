"use client";

import { useEffect, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { spDateString, type BusinessWindow } from "@/lib/business-hours";
import { collectOpenRounds, type SlaConversation } from "@/lib/sla-rounds";

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
  start_date: string;
  end_date: string;
}

interface LeadJoin {
  name: string | null;
  phone: string | null;
}

interface ConvRow {
  id: string;
  channel_id: string;
  lead_id: string | null;
  last_seller_response_at: string | null;
  leads: LeadJoin | null;
}

interface MsgRow {
  conversation_id: string;
  sent_by: string;
  created_at: string;
}

export interface OverdueLead {
  conversationId: string;
  leadId: string;
  leadName: string;
  leadPhone: string;
  channelId: string;
  userId: string;
  vendedorName: string;
  elapsedMinutes: number;
}

export interface OverdueData {
  leads: OverdueLead[];
  vendedores: { userId: string; name: string }[];
  isAdmin: boolean;
  loading: boolean;
}

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
  channelIds: string[]
): Promise<ConvRow[]> {
  if (channelIds.length === 0) return [];
  const PAGE = 1000;
  const all: ConvRow[] = [];
  let offset = 0;
  while (true) {
    const { data, error } = await supabase
      .from("conversations")
      .select("id, channel_id, lead_id, last_seller_response_at, leads(name, phone)")
      .in("channel_id", channelIds)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE - 1);
    if (error || !data || data.length === 0) break;
    all.push(...(data as unknown as ConvRow[]));
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
  const CHUNK = 200;
  const all: MsgRow[] = [];
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

export function useOverdueLeads(): OverdueData {
  const [leads, setLeads] = useState<OverdueLead[]>([]);
  const [vendedores, setVendedores] = useState<{ userId: string; name: string }[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  const fetchAndCompute = useCallback(async () => {
    const { data: userData } = await supabase.auth.getUser();
    const user = userData.user;
    const admin = user?.app_metadata?.role === "admin";
    setIsAdmin(admin);

    const [{ data: cfgData }, { data: ovData }, { data: settingsData }] = await Promise.all([
      supabase.from("sla_seller_config").select("*").eq("active", true),
      supabase.from("sla_overrides").select("user_id, start_date, end_date"),
      supabase.from("sla_settings").select("target_minutes").eq("id", 1).single(),
    ]);

    const allConfigs = (cfgData ?? []) as SellerConfigRow[];
    const overrides = (ovData ?? []) as OverrideRow[];
    const target = (settingsData?.target_minutes ?? 20) as number;

    const configs = admin
      ? allConfigs
      : allConfigs.filter((c) => c.user_id === user?.id);

    setVendedores(
      admin ? allConfigs.map((c) => ({ userId: c.user_id, name: c.display_name || "(sem nome)" })) : []
    );

    const channelIds = configs.map((c) => c.channel_id);
    const convs = await fetchConversations(supabase, channelIds);
    const msgs = await fetchMessages(supabase, convs.map((c) => c.id));

    const msgsByConv = new Map<string, MsgRow[]>();
    for (const m of msgs) {
      if (!msgsByConv.has(m.conversation_id)) msgsByConv.set(m.conversation_id, []);
      msgsByConv.get(m.conversation_id)!.push(m);
    }
    const convById = new Map<string, ConvRow>();
    for (const c of convs) convById.set(c.id, c);

    const convsByChannel = new Map<string, SlaConversation[]>();
    for (const c of convs) {
      if (!c.lead_id) continue;
      const slaConv: SlaConversation = {
        id: c.id,
        last_seller_response_at: c.last_seller_response_at,
        messages: msgsByConv.get(c.id) ?? [],
      };
      if (!convsByChannel.has(c.channel_id)) convsByChannel.set(c.channel_id, []);
      convsByChannel.get(c.channel_id)!.push(slaConv);
    }

    const now = new Date();
    const result: OverdueLead[] = [];

    for (const cfg of configs) {
      const win = windowFor(cfg, overrides);
      const channelConvs = convsByChannel.get(cfg.channel_id) ?? [];
      const open = collectOpenRounds(channelConvs, win, now);
      for (const o of open) {
        if (o.elapsedMinutes <= target) continue;
        const conv = convById.get(o.conversationId);
        if (!conv || !conv.lead_id) continue;
        const phone = conv.leads?.phone ?? "";
        result.push({
          conversationId: o.conversationId,
          leadId: conv.lead_id,
          leadName: conv.leads?.name || phone || "(sem nome)",
          leadPhone: phone,
          channelId: cfg.channel_id,
          userId: cfg.user_id,
          vendedorName: cfg.display_name || "(sem nome)",
          elapsedMinutes: o.elapsedMinutes,
        });
      }
    }

    result.sort((a, b) => b.elapsedMinutes - a.elapsedMinutes);
    setLeads(result);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    setLoading(true);
    fetchAndCompute();

    const channel = supabase
      .channel("overdue-leads-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "conversations" }, fetchAndCompute)
      .on("postgres_changes", { event: "*", schema: "public", table: "messages" }, fetchAndCompute)
      .subscribe();

    const ticker = setInterval(fetchAndCompute, 60_000);

    return () => {
      supabase.removeChannel(channel);
      clearInterval(ticker);
    };
  }, [fetchAndCompute]);

  return { leads, vendedores, isAdmin, loading };
}

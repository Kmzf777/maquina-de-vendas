import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

interface EvolutionChat {
  id?: string;
  remoteJid: string;
  pushName?: string | null;
  name?: string | null;
  lastMessage?: {
    messageTimestamp?: number;
    key?: { remoteJidAlt?: string };
    message?: Record<string, unknown>;
  } | null;
  unreadCount?: number;
}

function phoneFromJid(jid: string, alt?: string): string | null {
  const target = jid.endsWith("@lid") && alt ? alt : jid;
  const match = target.match(/^(\d+)@/);
  return match ? match[1] : null;
}

function extractLastMessageContent(msg: Record<string, unknown> | undefined | null): string {
  if (!msg) return "";
  if (typeof msg.conversation === "string") return msg.conversation;
  const ext = msg.extendedTextMessage as Record<string, unknown> | undefined;
  if (ext?.text) return ext.text as string;
  if (msg.imageMessage) return "[Imagem]";
  if (msg.audioMessage) return "[Audio]";
  if (msg.documentMessage) return "[Documento]";
  if (msg.videoMessage) return "[Video]";
  if (msg.stickerMessage) return "[Sticker]";
  return "";
}

/**
 * Fetch chats from Evolution API for a channel and return them
 * as Conversation-like objects (without writing to DB).
 */
async function fetchEvolutionConversations(channel: {
  id: string;
  name: string;
  phone: string;
  provider: string;
  provider_config: Record<string, string>;
}) {
  const config = channel.provider_config;
  const baseUrl = (config.api_url || "").replace(/\/+$/, "");
  const apiKey = config.api_key || "";
  const instanceName = config.instance || "";

  if (!baseUrl || !apiKey || !instanceName) return [];

  const res = await fetch(
    `${baseUrl}/chat/findChats/${encodeURIComponent(instanceName)}`,
    {
      method: "POST",
      headers: { apikey: apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({}),
      signal: AbortSignal.timeout(8000),
    }
  );

  if (!res.ok) return [];

  const rawChats: EvolutionChat[] = await res.json();
  if (!Array.isArray(rawChats)) return [];

  // Filter individual chats only (not groups)
  const conversations = rawChats
    .filter(
      (c) =>
        c.remoteJid?.endsWith("@s.whatsapp.net") ||
        c.remoteJid?.endsWith("@lid")
    )
    .map((chat) => {
      const altJid = chat.lastMessage?.key?.remoteJidAlt;
      const phone = phoneFromJid(chat.remoteJid, altJid);
      if (!phone) return null;

      const pushName = chat.pushName || chat.name || null;
      const lastMsgTimestamp = chat.lastMessage?.messageTimestamp;
      const lastMsgAt = lastMsgTimestamp
        ? new Date(lastMsgTimestamp * 1000).toISOString()
        : null;

      return {
        // Use a deterministic ID: channel_id + phone
        id: `evo_${channel.id}_${phone}`,
        lead_id: null,
        channel_id: channel.id,
        stage: "secretaria",
        status: "active",
        last_msg_at: lastMsgAt,
        created_at: lastMsgAt || new Date().toISOString(),
        // Nested objects matching the Conversation type
        leads: {
          id: `evo_lead_${phone}`,
          phone,
          name: pushName,
          company: null,
          stage: "secretaria",
          status: "active",
        },
        channels: {
          id: channel.id,
          name: channel.name,
          phone: channel.phone,
          provider: channel.provider,
        },
        // Extra field for Evolution-specific data
        _evo_remote_jid: chat.remoteJid,
        _evo_last_message: extractLastMessageContent(chat.lastMessage?.message),
      };
    })
    .filter(Boolean);

  return conversations;
}

export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");
  const status = searchParams.get("status");

  // 1. Get DB conversations
  let dbQuery = supabase
    .from("conversations")
    .select(
      "*, leads(id, phone, name, company, stage, status), channels(id, name, phone, provider), agent_profiles(id,name)"
    );

  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);

  const { data: dbConversations } = await dbQuery
    .order("last_msg_at", { ascending: false, nullsFirst: false })
    .limit(100);

  // 2. Get Evolution channels and fetch their chats
  let channelsQuery = supabase
    .from("channels")
    .select("id, name, phone, provider, provider_config")
    .eq("provider", "evolution")
    .eq("is_active", true);

  if (channelId) channelsQuery = channelsQuery.eq("id", channelId);

  const { data: evoChannels } = await channelsQuery;

  // Fetch Evolution chats in parallel (with error tolerance)
  const evoResults = await Promise.allSettled(
    (evoChannels || []).map((ch) =>
      fetchEvolutionConversations(
        ch as {
          id: string;
          name: string;
          phone: string;
          provider: string;
          provider_config: Record<string, string>;
        }
      )
    )
  );

  const evoConversations = evoResults.flatMap((r) =>
    r.status === "fulfilled" ? r.value : []
  );

  // 3. Merge: DB conversations take priority (they have real IDs)
  // Build a set of phones that already have DB conversations per channel
  const dbPhoneKeys = new Set(
    (dbConversations || []).map((c) => {
      const lead = c.leads as { phone?: string } | null;
      return `${c.channel_id}_${lead?.phone || ""}`;
    })
  );

  // Add Evolution conversations that don't already exist in DB
  const merged = [...(dbConversations || [])];
  for (const evoConv of evoConversations) {
    if (!evoConv) continue;
    const key = `${evoConv.channel_id}_${(evoConv.leads as { phone: string }).phone}`;
    if (!dbPhoneKeys.has(key)) {
      merged.push(evoConv);
    }
  }

  // Sort by last_msg_at descending
  merged.sort((a, b) => {
    const ta = a.last_msg_at ? new Date(a.last_msg_at).getTime() : 0;
    const tb = b.last_msg_at ? new Date(b.last_msg_at).getTime() : 0;
    return tb - ta;
  });

  return NextResponse.json(merged.slice(0, 100));
}

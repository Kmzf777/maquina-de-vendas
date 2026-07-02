import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";

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
  mode?: string;
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
        last_customer_message_at: null,
        created_at: lastMsgAt || new Date().toISOString(),
        // Nested objects matching the Conversation type
        leads: {
          id: `evo_lead_${phone}`,
          phone,
          name: pushName,
          company: null,
          stage: "secretaria",
          status: "active",
          last_customer_message_at: null,
        },
        channels: {
          id: channel.id,
          name: channel.name,
          phone: channel.phone,
          provider: channel.provider,
          mode: channel.mode,
        },
        // Extra field for Evolution-specific data
        _evo_remote_jid: chat.remoteJid,
        _evo_last_message: extractLastMessageContent(chat.lastMessage?.message),
        // Evolution messages have no role info — no "IA:" prefix possible
        last_message_text: extractLastMessageContent(chat.lastMessage?.message) || null,
        last_message_direction: null, // Evolution não tem info de role (fora de escopo — CLAUDE.md §6)
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

  // Determina quais channel_ids o usuário logado pode ver.
  // Falha de auth lança ChannelAccessError → respondemos 401, NUNCA [] silencioso
  // (um [] em erro é indistinguível de "zero conversas" e apaga a lista na UI).
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  // 1. Get DB conversations
  let dbQuery = supabase
    .from("conversations")
    .select(
      "*, first_seller_response_at, last_seller_response_at, leads(id, phone, name, company, stage, status, last_customer_message_at, ai_enabled, created_at, channel, on_hold, cnpj, razao_social, nome_fantasia, inscricao_estadual, endereco, telefone_comercial, email, instagram), channels(id, name, phone, provider, agent_profile_id, mode, agent_profiles(id, name, prompt_key)), agent_profiles(id, name, prompt_key)"
    );

  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);
  // Restringe ao conjunto de canais permitidos para o usuário logado
  if (allowedChannelIds !== null) {
    if (allowedChannelIds.length === 0) {
      // Usuário não tem nenhum canal — retorna lista vazia imediatamente
      return NextResponse.json([]);
    }
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }

  const { data: dbConversations, error: dbError } = await dbQuery
    .order("last_msg_at", { ascending: false, nullsFirst: false });
  // Não devolver [] silencioso em erro de query: a UI não distingue erro de
  // "zero conversas" e apagaria a lista. Responder 500 mantém o estado anterior.
  if (dbError) {
    return NextResponse.json({ error: dbError.message }, { status: 500 });
  }

  // Fetch last message text for meta_cloud conversations via RPC
  const metaConvIds = (dbConversations || [])
    .filter((c) => (c.channels as { provider?: string } | null)?.provider === "meta_cloud")
    .map((c) => c.id as string);

  const lastMsgMap = new Map<string, string>();
  const lastDirMap = new Map<string, "inbound" | "outbound">();
  if (metaConvIds.length > 0) {
    const { data: lastMsgs } = await supabase.rpc("get_last_messages", {
      conv_ids: metaConvIds,
    });
    for (const row of lastMsgs || []) {
      let prefix = "";
      if (row.sent_by === "seller") prefix = "Vendedor: ";
      else if (["broadcast", "campaign", "automation", "followup", "cadence"].includes(row.sent_by)) prefix = "Disparo: ";
      else if (row.role === "assistant") prefix = "IA: ";
      lastMsgMap.set(row.conversation_id, prefix + row.content);
      // role "user" = lead falou por último → inbound; caso contrário nós falamos → outbound
      lastDirMap.set(row.conversation_id, row.role === "user" ? "inbound" : "outbound");
    }
  }

  // Fetch active deal (pipeline + stage) for all DB conversation leads
  const allLeadIds = (dbConversations || [])
    .map((c) => (c.leads as { id?: string } | null)?.id)
    .filter(Boolean) as string[];

  type DealInfo = { pipeline_name: string; stage_label: string; stage_dot_color: string };
  const dealMap = new Map<string, DealInfo>();
  if (allLeadIds.length > 0) {
    const { data: dealRows } = await supabase.rpc("get_lead_deals", {
      lead_ids: allLeadIds,
    });
    for (const row of dealRows || []) {
      dealMap.set(row.lead_id, {
        pipeline_name: row.pipeline_name,
        stage_label: row.stage_label,
        stage_dot_color: row.stage_dot_color,
      });
    }
  }

  // 2. Get Evolution channels and fetch their chats
  let channelsQuery = supabase
    .from("channels")
    .select("id, name, phone, provider, provider_config, mode")
    .eq("provider", "evolution")
    .eq("is_active", true);

  if (channelId) channelsQuery = channelsQuery.eq("id", channelId);
  if (allowedChannelIds !== null && allowedChannelIds.length > 0) {
    channelsQuery = channelsQuery.in("id", allowedChannelIds);
  }

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
          mode?: string;
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

  // Add last_message_text + deal info to DB conversations
  const dbWithLastMsg = (dbConversations || []).map((c) => {
    const leadId = (c.leads as { id?: string } | null)?.id ?? "";
    const deal = dealMap.get(leadId);
    return {
      ...c,
      last_message_text: lastMsgMap.get(c.id as string) ?? null,
      last_message_direction: lastDirMap.get(c.id as string) ?? null,
      deal_pipeline_name: deal?.pipeline_name ?? null,
      deal_stage_label: deal?.stage_label ?? null,
      deal_stage_dot_color: deal?.stage_dot_color ?? null,
    };
  });

  // Add Evolution conversations that don't already exist in DB
  const merged = [...dbWithLastMsg];
  for (const evoConv of evoConversations) {
    if (!evoConv) continue;
    const key = `${evoConv.channel_id}_${(evoConv.leads as { phone: string }).phone}`;
    if (!dbPhoneKeys.has(key)) {
      merged.push(evoConv);
    }
  }

  // Sort by last_msg_at descending, falling back to created_at to avoid
  // proactively-created conversations (null last_msg_at) sinking to 1970.
  const sortTs = (c: { last_msg_at?: string | null; created_at?: string | null }): number => {
    const t = c.last_msg_at ?? c.created_at;
    return t ? new Date(t).getTime() : 0;
  };
  merged.sort((a, b) => sortTs(b) - sortTs(a));

  return NextResponse.json(merged);
}

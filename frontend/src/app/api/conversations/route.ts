import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import {
  conversationSelect,
  enrichConversations,
  type EnrichableConversation,
} from "@/lib/supabase/conversation-enrichment";
import {
  CONVERSATIONS_PAGE_SIZE,
  cursorOrFilter,
  decodeCursor,
  parseTabFilter,
  splitPage,
} from "./list-params";

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
  // Filtro por lead: usado pelo deep-link `/conversas?lead_id=...` e pelas conversas
  // irmãs (mesmo lead em outro canal).
  const leadId = searchParams.get("lead_id");
  // Aba da lista como filtro de SERVIDOR: filtrar no cliente só enxergava a página
  // carregada (e antes, o teto de 1.000 linhas do PostgREST).
  const tabFilter = parseTabFilter(searchParams.get("tab"));
  const rawCursor = searchParams.get("cursor");
  const cursor = decodeCursor(rawCursor);
  if (rawCursor && !cursor) {
    return NextResponse.json({ error: "invalid cursor" }, { status: 400 });
  }

  // Determina quais channel_ids o usuário logado pode ver.
  // Falha de auth lança ChannelAccessError → respondemos 401, NUNCA [] silencioso
  // (uma lista vazia em erro é indistinguível de "zero conversas" e apaga a lista na UI).
  let allowedChannelIds: string[] | null;
  try {
    allowedChannelIds = await getAllowedChannelIds(supabase);
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    }
    throw err;
  }

  if (allowedChannelIds !== null && allowedChannelIds.length === 0) {
    // Usuário não tem nenhum canal — página vazia imediatamente
    return NextResponse.json({ conversations: [], next_cursor: null });
  }

  // 1. Página de conversas do banco. A aba por estágio filtra pelo lead embutido, o
  // que exige INNER JOIN (com o LEFT o filtro só esvaziaria `leads`).
  let dbQuery = supabase
    .from("conversations")
    .select(conversationSelect({ innerLead: tabFilter.kind === "stage" }));

  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);
  if (leadId) dbQuery = dbQuery.eq("lead_id", leadId);
  // BLOQUEIO: a conversa de um lead bloqueado SOME do /conversas (decisão de produto).
  // `block_lead` carimba conversations.status = 'blocked'; o filtro fica aqui, na fonte
  // da listagem, para valer inclusive no deep-link ?lead_id=. O histórico não some do
  // sistema — continua acessível pelo funil Blacklist e pela tela de leads.
  dbQuery = dbQuery.neq("status", "blocked");
  // Restringe ao conjunto de canais permitidos para o usuário logado
  if (allowedChannelIds !== null) dbQuery = dbQuery.in("channel_id", allowedChannelIds);

  if (tabFilter.kind === "unread") dbQuery = dbQuery.gt("unread_count", 0);
  else if (tabFilter.kind === "no_lead") dbQuery = dbQuery.is("lead_id", null);
  else if (tabFilter.kind === "stage") dbQuery = dbQuery.eq("leads.stage", tabFilter.stage);

  // Keyset: só linhas DEPOIS da última entregue. Na cauda (last_msg_at nulo) a
  // ordem é só pelo id.
  if (cursor) {
    dbQuery = cursor.t
      ? dbQuery.or(cursorOrFilter(cursor.t, cursor.id))
      : dbQuery.is("last_msg_at", null).lt("id", cursor.id);
  }

  const { data: dbRows, error: dbError } = await dbQuery
    .order("last_msg_at", { ascending: false, nullsFirst: false })
    .order("id", { ascending: false })
    .limit(CONVERSATIONS_PAGE_SIZE + 1);
  // Não devolver lista vazia silenciosa em erro de query: a UI não distingue erro de
  // "zero conversas" e apagaria a lista. Responder 500 mantém o estado anterior.
  if (dbError) {
    return NextResponse.json({ error: dbError.message }, { status: 500 });
  }
  // O select é montado em runtime, então o supabase-js não infere a forma da
  // linha — o contrato real está em EnrichableConversation.
  const { rows: dbConversations, next_cursor } = splitPage(
    (dbRows ?? []) as unknown as EnrichableConversation[],
    CONVERSATIONS_PAGE_SIZE,
  );

  // Add last_message_text + deal info to DB conversations
  const dbWithLastMsg = await enrichConversations(supabase, dbConversations);

  // 2. Evolution (legado, CLAUDE.md §6): só na primeira página da aba "todos", como
  // antes — as conversas Evolution não têm cursor nem estágio/não lidas.
  if (cursor || tabFilter.kind !== "all" || leadId) {
    return NextResponse.json({ conversations: dbWithLastMsg, next_cursor });
  }

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
  if (evoConversations.length === 0) {
    return NextResponse.json({ conversations: dbWithLastMsg, next_cursor });
  }

  // 3. Merge: DB conversations take priority (they have real IDs)
  const dbPhoneKeys = new Set(
    dbConversations.map((c) => {
      const lead = c.leads as { phone?: string } | null;
      return `${c.channel_id}_${lead?.phone || ""}`;
    })
  );
  const merged: EnrichableConversation[] = [...dbWithLastMsg];
  for (const evoConv of evoConversations) {
    if (!evoConv) continue;
    const key = `${evoConv.channel_id}_${(evoConv.leads as { phone: string }).phone}`;
    if (!dbPhoneKeys.has(key)) {
      merged.push(evoConv as unknown as EnrichableConversation);
    }
  }

  // Sort by last_msg_at descending, falling back to created_at to avoid
  // proactively-created conversations (null last_msg_at) sinking to 1970.
  const sortTs = (c: { last_msg_at?: string | null; created_at?: string | null }): number => {
    const t = c.last_msg_at ?? c.created_at;
    return t ? new Date(t).getTime() : 0;
  };
  merged.sort((a, b) => sortTs(b) - sortTs(a));

  return NextResponse.json({ conversations: merged, next_cursor });
}

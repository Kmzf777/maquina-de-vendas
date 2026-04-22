import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

interface EvolutionRecord {
  key?: {
    fromMe?: boolean;
    id?: string;
    remoteJid?: string;
  };
  message?: {
    conversation?: string;
    extendedTextMessage?: { text?: string };
    imageMessage?: { caption?: string };
    audioMessage?: unknown;
    documentMessage?: { fileName?: string };
    stickerMessage?: unknown;
    videoMessage?: { caption?: string };
  };
  messageTimestamp?: number;
  pushName?: string;
}

function extractContent(record: EvolutionRecord): string {
  const m = record.message;
  if (!m) return "";
  if (typeof m.conversation === "string") return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
  const img = m.imageMessage;
  if (img?.caption) return img.caption;
  if (img) return "[Imagem]";
  if (m.audioMessage) return "[Audio]";
  const doc = m.documentMessage;
  if (doc?.fileName) return `[Documento: ${doc.fileName}]`;
  if (m.stickerMessage) return "[Sticker]";
  const vid = m.videoMessage;
  if (vid?.caption) return vid.caption;
  if (vid) return "[Video]";
  return "[Midia]";
}

async function fetchEvolutionMessages(
  config: Record<string, string>,
  phone: string
) {
  const baseUrl = (config.api_url || "").replace(/\/+$/, "");
  const apiKey = config.api_key || "";
  const instanceName = config.instance || "";

  if (!baseUrl || !apiKey || !instanceName) return [];

  const MAX_PAGES = 5;
  let allRecords: EvolutionRecord[] = [];
  let currentPage = 1;
  let totalPages = 1;

  do {
    const res = await fetch(
      `${baseUrl}/chat/findMessages/${encodeURIComponent(instanceName)}`,
      {
        method: "POST",
        headers: { apikey: apiKey, "Content-Type": "application/json" },
        body: JSON.stringify({
          where: { key: { remoteJid: `${phone}@s.whatsapp.net` } },
          page: currentPage,
        }),
        signal: AbortSignal.timeout(8000),
      }
    );

    if (!res.ok) break;

    const data = await res.json();

    if (data?.messages?.records) {
      allRecords = allRecords.concat(data.messages.records);
      totalPages = data.messages.pages || 1;
    } else if (Array.isArray(data)) {
      allRecords = data;
      break;
    } else {
      break;
    }

    currentPage++;
  } while (currentPage <= totalPages && currentPage <= MAX_PAGES);

  return allRecords
    .filter((r) => extractContent(r).length > 0)
    .map((record) => {
      const fromMe = record.key?.fromMe ?? false;
      const ts = record.messageTimestamp
        ? new Date(record.messageTimestamp * 1000).toISOString()
        : new Date().toISOString();

      return {
        id: record.key?.id || crypto.randomUUID(),
        role: fromMe ? "assistant" : "user",
        content: extractContent(record),
        sent_by: fromMe ? "agent" : "user",
        created_at: ts,
      };
    })
    .sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  // Handle synthetic Evolution conversation IDs: evo_{channelId}_{phone}
  if (id.startsWith("evo_")) {
    const parts = id.replace("evo_", "").split("_");
    // channelId is a UUID (contains dashes), phone is the rest
    // Format: evo_{uuid}_{phone} where uuid has 4 dashes
    const channelId = parts.slice(0, 5).join("-"); // reassemble UUID from split
    // Wait — UUIDs have dashes not underscores. Let me parse differently.
    // Actually the ID is: evo_ + channelId + _ + phone
    // channelId is a UUID like "abc-def-ghi" which has dashes, not underscores
    // So after removing "evo_", the format is: {uuid}_{phone}
    // UUID format: 8-4-4-4-12 = 36 chars
    const rest = id.slice(4); // remove "evo_"
    const channelId2 = rest.slice(0, 36);
    const phone = rest.slice(37); // skip the underscore after UUID

    if (!channelId2 || !phone) {
      return NextResponse.json({ error: "Invalid conversation ID" }, { status: 400 });
    }

    const { data: channel } = await supabase
      .from("channels")
      .select("provider_config")
      .eq("id", channelId2)
      .single();

    if (!channel) {
      return NextResponse.json({ error: "Channel not found" }, { status: 404 });
    }

    try {
      const messages = await fetchEvolutionMessages(
        channel.provider_config as Record<string, string>,
        phone
      );
      return NextResponse.json(messages);
    } catch {
      return NextResponse.json([]);
    }
  }

  // Regular DB conversation
  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("*, leads(id, phone), channels(id, provider, provider_config)")
    .eq("id", id)
    .single();

  if (convError || !conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  const channel = conv.channels as {
    id: string;
    provider: string;
    provider_config: Record<string, string>;
  } | null;
  const lead = conv.leads as { id: string; phone: string } | null;

  // For Evolution channels: fetch from Evolution API
  if (channel?.provider === "evolution" && lead?.phone) {
    try {
      const messages = await fetchEvolutionMessages(
        channel.provider_config,
        lead.phone
      );
      return NextResponse.json(messages);
    } catch {
      // Fallback to DB
    }
  }

  // Fallback: DB messages
  const { data, error } = await supabase
    .from("messages")
    .select("*")
    .eq("conversation_id", id)
    .order("created_at", { ascending: true })
    .limit(200);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { describeMetaReactionError } from "@/lib/meta-error";

const META_API_VERSION = "v21.0";

// Reação do operador a uma mensagem do chat (plano 11/07, item 3).
// Mesmo padrão do send/route.ts: chamada direta à Graph API + insert em
// `messages`. A linha persiste com o MESMO shape das reações inbound
// (message_type="reaction", metadata={emoji, target_wamid}) — zero migração.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;

  let body: { target_wamid?: unknown; emoji?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const targetWamid = typeof body.target_wamid === "string" ? body.target_wamid.trim() : "";
  const emoji = typeof body.emoji === "string" ? body.emoji.trim() : "";
  if (!targetWamid) {
    return NextResponse.json({ error: "target_wamid is required" }, { status: 400 });
  }
  if (!emoji) {
    return NextResponse.json({ error: "emoji is required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("*, leads(id, phone), channels(id, provider, provider_config)")
    .eq("id", conversationId)
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

  if (!channel || !lead?.phone) {
    return NextResponse.json({ error: "Invalid conversation data" }, { status: 400 });
  }
  if (channel.provider !== "meta_cloud") {
    return NextResponse.json(
      { error: "Reações disponíveis apenas para Meta Cloud" },
      { status: 400 }
    );
  }

  const { phone_number_id, access_token, api_version } = channel.provider_config;
  const version = api_version || META_API_VERSION;
  if (!phone_number_id || !access_token) {
    return NextResponse.json({ error: "Canal não configurado corretamente" }, { status: 500 });
  }

  try {
    const res = await fetch(
      `https://graph.facebook.com/${version}/${phone_number_id}/messages`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messaging_product: "whatsapp",
          to: lead.phone,
          type: "reaction",
          reaction: { message_id: targetWamid, emoji },
        }),
      }
    );

    if (!res.ok) {
      const errText = await res.text();
      console.error("[react] Meta send failed:", errText);
      const info = describeMetaReactionError(errText);
      return NextResponse.json({ error: info.error }, { status: info.status });
    }

    let sentWamid: string | null = null;
    try {
      const json = (await res.json()) as { messages?: { id?: string }[] };
      sentWamid = json?.messages?.[0]?.id ?? null;
    } catch {
      // aceito pela Meta; wamid ausente não falha o request
    }

    const insertData: Record<string, unknown> = {
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: emoji,
      sent_by: "seller",
      stage: conv.stage || "secretaria",
      message_type: "reaction",
      metadata: { emoji, target_wamid: targetWamid },
    };
    if (sentWamid) {
      insertData.wamid = sentWamid;
      insertData.delivery_status = "accepted";
    }
    await supabase.from("messages").insert(insertData);

    // Reação zera o badge de não-lidas mas NÃO carimba last_msg_at — reagir não
    // deve reordenar o inbox nem mexer na janela (só mensagem real faz isso).
    await supabase
      .from("conversations")
      .update({ unread_count: 0 })
      .eq("id", conversationId);

    return NextResponse.json({ status: "sent" });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send reaction";
    console.error("[react] unhandled error:", msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

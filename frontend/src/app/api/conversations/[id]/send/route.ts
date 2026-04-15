import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

function parseEvoId(id: string): { channelId: string; phone: string } | null {
  if (!id.startsWith("evo_")) return null;
  const rest = id.slice(4);
  const channelId = rest.slice(0, 36);
  const phone = rest.slice(37);
  if (!channelId || !phone) return null;
  return { channelId, phone };
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;
  const { text } = await request.json();

  if (!text?.trim()) {
    return NextResponse.json({ error: "text is required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // Handle synthetic Evolution conversation IDs
  const evoInfo = parseEvoId(conversationId);
  if (evoInfo) {
    const { data: channel } = await supabase
      .from("channels")
      .select("provider, provider_config")
      .eq("id", evoInfo.channelId)
      .single();

    if (!channel) {
      return NextResponse.json({ error: "Channel not found" }, { status: 404 });
    }

    try {
      await sendViaEvolution(
        channel.provider_config as Record<string, string>,
        evoInfo.phone,
        text.trim()
      );

      // Save message to DB — look up lead by phone
      const { data: lead } = await supabase
        .from("leads")
        .select("id, stage")
        .eq("phone", evoInfo.phone)
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      if (lead) {
        await supabase.from("messages").insert({
          lead_id: lead.id,
          role: "assistant",
          content: text.trim(),
          stage: lead.stage || "secretaria",
        });
      }

      return NextResponse.json({ status: "sent" });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to send";
      return NextResponse.json({ error: msg }, { status: 500 });
    }
  }

  // Regular DB conversation
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

  try {
    if (channel.provider === "evolution") {
      await sendViaEvolution(channel.provider_config, lead.phone, text.trim());
    } else if (channel.provider === "meta_cloud") {
      await sendViaMeta(channel.provider_config, lead.phone, text.trim());
    } else {
      return NextResponse.json({ error: "Unknown provider" }, { status: 400 });
    }

    // Save message to DB
    await supabase.from("messages").insert({
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: text.trim(),
      stage: conv.stage || "secretaria",
    });

    // Update conversation last_msg_at
    await supabase
      .from("conversations")
      .update({ last_msg_at: new Date().toISOString() })
      .eq("id", conversationId);

    return NextResponse.json({ status: "sent" });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

async function sendViaEvolution(
  config: Record<string, string>,
  phone: string,
  text: string
) {
  const baseUrl = (config.api_url || "").replace(/\/+$/, "");
  const apiKey = config.api_key || "";
  const instanceName = config.instance || "";

  const res = await fetch(
    `${baseUrl}/message/sendText/${encodeURIComponent(instanceName)}`,
    {
      method: "POST",
      headers: { apikey: apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({ number: phone, text }),
    }
  );

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Evolution API error: ${err}`);
  }
}

async function sendViaMeta(
  config: Record<string, string>,
  phone: string,
  text: string
) {
  const phoneNumberId = config.phone_number_id || "";
  const accessToken = config.access_token || "";

  const res = await fetch(
    `https://graph.facebook.com/v21.0/${phoneNumberId}/messages`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        messaging_product: "whatsapp",
        to: phone,
        type: "text",
        text: { body: text },
      }),
    }
  );

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Meta API error: ${err}`);
  }
}

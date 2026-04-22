import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { leadId, text } = await request.json();

  if (!leadId || !text) {
    return NextResponse.json({ error: "leadId and text required" }, { status: 400 });
  }

  // Fetch lead
  const { data: lead, error: leadError } = await supabase
    .from("leads")
    .select("*")
    .eq("id", leadId)
    .single();

  if (leadError || !lead) {
    return NextResponse.json({ error: "Lead not found" }, { status: 404 });
  }

  // Send via appropriate channel
  try {
    if (lead.channel === "evolution") {
      await sendViaEvolution(lead.phone, text);
    } else {
      await sendViaMeta(lead.phone, text);
    }
  } catch (err) {
    console.error("Failed to send message:", err);
    return NextResponse.json({ error: "Failed to send" }, { status: 500 });
  }

  // Save message to DB
  await supabase.from("messages").insert({
    lead_id: leadId,
    role: "assistant",
    content: text,
    stage: lead.stage,
    sent_by: "seller",
  });

  // Update last_msg_at
  await supabase
    .from("leads")
    .update({ last_msg_at: new Date().toISOString() })
    .eq("id", leadId);

  return NextResponse.json({ ok: true });
}

async function sendViaEvolution(phone: string, text: string) {
  const url = process.env.EVOLUTION_API_URL!;
  const key = process.env.EVOLUTION_API_KEY!;
  const instance = process.env.EVOLUTION_INSTANCE!;

  const res = await fetch(`${url}/message/sendText/${instance}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: key,
    },
    body: JSON.stringify({
      number: phone,
      text: text,
    }),
  });

  if (!res.ok) {
    throw new Error(`Evolution API error: ${res.status}`);
  }
}

async function sendViaMeta(phone: string, text: string) {
  const phoneNumberId = process.env.META_PHONE_NUMBER_ID!;
  const accessToken = process.env.META_ACCESS_TOKEN!;
  const apiVersion = process.env.META_API_VERSION || "v21.0";

  const res = await fetch(
    `https://graph.facebook.com/${apiVersion}/${phoneNumberId}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
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
    throw new Error(`Meta API error: ${res.status}`);
  }
}

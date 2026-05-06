import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;
  const body = await request.json();
  const { template_name, template_language_code = "pt_BR", template_variables } = body;

  if (!template_name) {
    return NextResponse.json({ error: "template_name is required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("id, stage, leads(id, phone), channels(id, provider, provider_config)")
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
      { error: "Template dispatch only supported for Meta Cloud channels" },
      { status: 400 }
    );
  }

  try {
    await sendTemplateViaMeta(
      channel.provider_config,
      lead.phone,
      template_name,
      template_language_code,
      template_variables ?? null,
    );
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send template";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  // Resolve template body text from local DB for the message record
  let content = `[Template: ${template_name}]`;
  try {
    const { data: tplRow } = await supabase
      .from("message_templates")
      .select("components")
      .eq("name", template_name)
      .limit(1)
      .maybeSingle();

    if (tplRow?.components) {
      const bodyComp = (tplRow.components as { type: string; text?: string }[]).find(
        (c) => c.type === "BODY"
      );
      if (bodyComp?.text) content = bodyComp.text;
    }
  } catch {
    // fallback to placeholder — non-fatal
  }

  await supabase.from("messages").insert({
    lead_id: lead.id,
    conversation_id: conversationId,
    role: "assistant",
    content,
    sent_by: "broadcast",
  });

  await supabase
    .from("conversations")
    .update({
      status: "template_sent",
      last_msg_at: new Date().toISOString(),
    })
    .eq("id", conversationId);

  return NextResponse.json({ status: "sent" });
}

async function sendTemplateViaMeta(
  config: Record<string, string>,
  to: string,
  templateName: string,
  languageCode: string,
  variables: Record<string, string> | null,
) {
  const phoneNumberId = config.phone_number_id ?? "";
  const accessToken = config.access_token ?? "";
  const apiVersion = config.api_version ?? "v21.0";

  const template: Record<string, unknown> = {
    name: templateName,
    language: { code: languageCode },
  };

  if (variables && Object.keys(variables).length > 0) {
    const parameters = Object.entries(variables).map(([k, v]) => ({
      type: "text",
      parameter_name: k,
      text: String(v),
    }));
    template.components = [{ type: "body", parameters }];
  }

  const res = await fetch(
    `https://graph.facebook.com/${apiVersion}/${phoneNumberId}/messages`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        messaging_product: "whatsapp",
        to,
        type: "template",
        template,
      }),
    }
  );

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Meta API ${res.status}: ${err}`);
  }

  return res.json();
}

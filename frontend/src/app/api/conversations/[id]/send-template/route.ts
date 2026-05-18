import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;
  const body = await request.json();
  const { template_name, template_language_code = "pt_BR", template_variables, template_body: providedBody } = body;

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

  const channel = conv.channels as unknown as {
    id: string;
    provider: string;
    provider_config: Record<string, string>;
  } | null;
  const lead = conv.leads as unknown as { id: string; phone: string } | null;

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

  // Resolve template body text for the message record.
  // Priority: (1) body passed by client (already fetched by modal), (2) local DB, (3) Meta API.
  let content = `[Template: ${template_name}]`;

  if (providedBody && typeof providedBody === "string" && providedBody.trim()) {
    content = providedBody;
  } else {
    // 1. Local message_templates table
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
      // continue to Meta API fallback
    }

    // 2. Meta API fallback — mirrors _render_template_body in the broadcast worker
    if (content === `[Template: ${template_name}]`) {
      const cfg = channel.provider_config;
      const wabaId = cfg.waba_id;
      const accessToken = cfg.access_token;
      const apiVersion = cfg.api_version ?? "v21.0";

      if (wabaId && accessToken) {
        try {
          const metaRes = await fetch(
            `https://graph.facebook.com/${apiVersion}/${wabaId}/message_templates?name=${encodeURIComponent(template_name)}`,
            { headers: { Authorization: `Bearer ${accessToken}` } }
          );
          if (metaRes.ok) {
            const metaData = await metaRes.json();
            const tplData = (metaData.data ?? [])[0] as {
              id?: string; language?: string; category?: string;
              components?: { type: string; text?: string }[];
            } | undefined;
            if (tplData?.components) {
              const bodyComp = tplData.components.find((c) => c.type === "BODY");
              if (bodyComp?.text) {
                content = bodyComp.text;
                // Auto-sync to local DB so next call hits the fast path
                supabase.from("message_templates").insert({
                  channel_id: channel.id,
                  name: template_name,
                  language: tplData.language ?? template_language_code,
                  requested_category: tplData.category ?? "UTILITY",
                  category: tplData.category ?? "UTILITY",
                  components: tplData.components,
                  meta_template_id: tplData.id,
                  status: "approved",
                }).then(() => {}).catch(() => {});
              }
            }
          }
        } catch {
          // Meta API fallback failed — keep placeholder
        }
      }
    }
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

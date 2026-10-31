// Envio de modelo (template) pela Meta e gravação da mensagem enviada. Compartilhado
// pelo disparo de modelo numa conversa existente (`/api/conversations/[id]/send-template`)
// e pelo início de conversa com lead sem conversa (`/api/leads/[id]/iniciar-conversa`).
// Código movido da rota send-template sem mudança de comportamento.
import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;

/**
 * A Meta respondeu e RECUSOU o envio (HTTP não-ok): é certo que a mensagem não saiu.
 * Falha de rede, timeout ou JSON inválido NÃO viram esta classe — nesses casos o envio
 * é incerto (a Meta pode ter aceitado), e quem chama não deve desfazer nada.
 */
export class MetaRecusou extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MetaRecusou";
  }
}

export async function sendTemplateViaMeta(
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

  const bodyVars = variables
    ? Object.entries(variables).filter(([k]) => !k.startsWith("__"))
    : [];
  if (bodyVars.length > 0) {
    const paramsType = variables?.["__params_type__"] ?? "named";
    let parameters: Record<string, unknown>[];
    if (paramsType === "positional") {
      parameters = bodyVars
        .sort(([a], [b]) => (parseInt(a) || 999) - (parseInt(b) || 999))
        .map(([, v]) => ({ type: "text", text: String(v) }));
    } else {
      parameters = bodyVars.map(([k, v]) => ({
        type: "text",
        parameter_name: k,
        text: String(v),
      }));
    }
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
    throw new MetaRecusou(`Meta API ${res.status}: ${err}`);
  }

  return res.json();
}

/** wamid devolvido pela Meta no envio, ou null. */
export function wamidDaResposta(metaJson: unknown): string | null {
  const json = metaJson as { messages?: { id?: string }[] } | null;
  return json?.messages?.[0]?.id ?? null;
}

export interface TemplateEnviado {
  conversationId: string;
  leadId: string;
  /** Canal do envio: `id` e `provider_config` servem ao fallback que busca o corpo na Meta. */
  channel: { id: string; provider_config: Record<string, string> };
  templateName: string;
  templateLanguageCode: string;
  /** Corpo já renderizado pelo cliente (modal), se veio. */
  templateBody?: unknown;
  sentWamid: string | null;
}

/**
 * Grava o modelo enviado como mensagem do vendedor e marca a conversa `template_sent`.
 * Chamar SÓ depois de `sendTemplateViaMeta` dar certo.
 */
export async function registrarTemplateEnviado(
  supabase: ServiceSupabase,
  {
    conversationId,
    leadId,
    channel,
    templateName: template_name,
    templateLanguageCode: template_language_code,
    templateBody: providedBody,
    sentWamid,
  }: TemplateEnviado,
): Promise<void> {
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
                }).then(() => {}, () => {});
              }
            }
          }
        } catch {
          // Meta API fallback failed — keep placeholder
        }
      }
    }
  }

  // Template mandado à mão pelo vendedor no CRM é mensagem DO VENDEDOR (sent_by='seller'):
  // conta como "closer assumiu" (D4) e fecha a rodada de SLA. O selo `metadata.template`
  // separa do texto livre. Disparo em massa continua 'broadcast' (outro caminho).
  const insertData: Record<string, unknown> = {
    lead_id: leadId,
    conversation_id: conversationId,
    role: "assistant",
    content,
    sent_by: "seller",
    metadata: { template: true, template_name },
  };
  if (sentWamid) {
    insertData.wamid = sentWamid;
    insertData.delivery_status = "accepted";
  }
  await supabase.from("messages").insert(insertData);

  await supabase
    .from("conversations")
    .update({
      status: "template_sent",
      last_msg_at: new Date().toISOString(),
    })
    .eq("id", conversationId);
}

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { isLeadBlocked, MENSAGEM_LEAD_BLOQUEADO } from "@/lib/supabase/lead-blocked";
import { resolveSendTarget, LEAD_SEND_FIELDS, type SendTargetLead } from "@/lib/whatsapp/send-target";
import { registrarTemplateEnviado, sendTemplateViaMeta, wamidDaResposta } from "@/lib/meta-template";

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
    .select(`id, stage, leads(id, ${LEAD_SEND_FIELDS}, opt_out), channels(id, provider, provider_config)`)
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
  const lead = conv.leads as unknown as ({ id: string; opt_out?: boolean | null } & SendTargetLead) | null;

  // Modelo é disparo FRIO (pode ser o 1º contato): o wa_id só vale com procedência,
  // senão vai para o phone E.164 — mesma regra do backend (require_inbound_provenance).
  const target = resolveSendTarget(lead, { requireInboundProvenance: true });
  if (!channel || !lead || !target) {
    return NextResponse.json({ error: "Invalid conversation data" }, { status: 400 });
  }

  if (channel.provider !== "meta_cloud") {
    return NextResponse.json(
      { error: "Template dispatch only supported for Meta Cloud channels" },
      { status: 400 }
    );
  }

  // BLOQUEIO (guard mais grave da feature): template é disparo ATIVO, fora da janela
  // de 24h, e esta rota fala DIRETO com a graph.facebook.com — nenhum guard do FastAPI
  // a cobre. Mandar template para quem pediu para sair é justamente o que gera denúncia
  // e banimento do número na Meta. Por isso o guard fica ANTES de sendTemplateViaMeta:
  // depois do POST não há como desfazer o envio.
  if (await isLeadBlocked(supabase, lead.id, lead.opt_out)) {
    return NextResponse.json({ error: MENSAGEM_LEAD_BLOQUEADO }, { status: 403 });
  }

  let sentWamid: string | null = null;
  try {
    sentWamid = wamidDaResposta(
      await sendTemplateViaMeta(
        channel.provider_config,
        target,
        template_name,
        template_language_code,
        template_variables ?? null,
      ),
    );
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Failed to send template";
    return NextResponse.json({ error: msg }, { status: 502 });
  }

  await registrarTemplateEnviado(supabase, {
    conversationId,
    leadId: lead.id,
    channel,
    templateName: template_name,
    templateLanguageCode: template_language_code,
    templateBody: providedBody,
    sentWamid,
  });

  return NextResponse.json({ status: "sent" });
}

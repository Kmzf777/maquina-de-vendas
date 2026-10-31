import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { isLeadBlocked, MENSAGEM_LEAD_BLOQUEADO } from "@/lib/supabase/lead-blocked";
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
    .select("id, stage, leads(id, phone, opt_out), channels(id, provider, provider_config)")
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
  const lead = conv.leads as unknown as { id: string; phone: string; opt_out?: boolean | null } | null;

  if (!channel || !lead?.phone) {
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
        lead.phone,
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

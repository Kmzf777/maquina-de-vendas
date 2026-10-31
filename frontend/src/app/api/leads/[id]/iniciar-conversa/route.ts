// Iniciar conversa com lead sem conversa (cartão 70d844a6). Cria a conversa do par
// lead+número e manda um modelo aprovado. Mesmos guards do disparo de modelo
// (send-template), e mais: acesso ao número e telefone utilizável. Só se a Meta RECUSAR
// (MetaRecusou) a conversa criada AQUI é desfeita — nunca a que já existia. Falha
// incerta (rede, timeout, JSON) não desfaz nada: a mensagem pode ter saído.
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getAllowedChannelIds, ChannelAccessError } from "@/lib/supabase/channel-access";
import { isLeadBlocked, MENSAGEM_LEAD_BLOQUEADO } from "@/lib/supabase/lead-blocked";
import {
  MetaRecusou,
  sendTemplateViaMeta,
  registrarTemplateEnviado,
  wamidDaResposta,
} from "@/lib/meta-template";
import { telefoneWhatsapp } from "@/lib/telefone-whatsapp";

type Ctx = { params: Promise<{ id: string }> };
type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;

/** Canais permitidos ao usuário (null = admin, todos) ou a resposta 401. */
async function permitidos(
  supabase: ServiceSupabase,
): Promise<{ ids: string[] | null } | { erro: NextResponse }> {
  try {
    return { ids: await getAllowedChannelIds(supabase) };
  } catch (err) {
    if (err instanceof ChannelAccessError) {
      return { erro: NextResponse.json({ error: "Unauthorized" }, { status: 401 }) };
    }
    throw err;
  }
}

/** Lead, telefone utilizável e os números Meta que o usuário pode usar. */
export async function GET(_request: NextRequest, { params }: Ctx) {
  const { id: leadId } = await params;
  const supabase = await getServiceSupabase();

  const acesso = await permitidos(supabase);
  if ("erro" in acesso) return acesso.erro;

  const { data: lead } = await supabase
    .from("leads")
    .select("id, name, phone, company")
    .eq("id", leadId)
    .maybeSingle();
  if (!lead) {
    return NextResponse.json({ error: "Lead not found" }, { status: 404 });
  }

  const { data: canais, error } = await supabase
    .from("channels")
    .select("id, name, provider")
    .eq("provider", "meta_cloud")
    .order("name");
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const visiveis = ((canais ?? []) as { id: string; name: string }[])
    .filter((c) => acesso.ids === null || acesso.ids.includes(c.id))
    .map((c) => ({ id: c.id, name: c.name }));

  return NextResponse.json({
    lead: { id: lead.id, name: lead.name, phone: lead.phone, company: lead.company },
    telefone: telefoneWhatsapp(lead.phone as string | null),
    canais: visiveis,
  });
}

/** Cria (se preciso) a conversa do par lead+número e envia o modelo. Guards antes do envio. */
export async function POST(request: NextRequest, { params }: Ctx) {
  const { id: leadId } = await params;
  const body = await request.json().catch(() => null);
  const {
    channel_id,
    template_name,
    template_language_code = "pt_BR",
    template_variables,
    template_body,
  } = (body ?? {}) as Record<string, unknown>;

  if (!channel_id || typeof channel_id !== "string" || !template_name || typeof template_name !== "string") {
    return NextResponse.json({ error: "channel_id and template_name are required" }, { status: 400 });
  }

  const supabase = await getServiceSupabase();

  // 1. Acesso ao número.
  const acesso = await permitidos(supabase);
  if ("erro" in acesso) return acesso.erro;

  const { data: channel } = await supabase
    .from("channels")
    .select("id, name, provider, provider_config")
    .eq("id", channel_id)
    .maybeSingle();
  if (!channel || (acesso.ids !== null && !acesso.ids.includes(channel.id))) {
    return NextResponse.json({ error: "Sem acesso a este número" }, { status: 403 });
  }

  // 2. Só Meta Cloud dispara modelo.
  if (channel.provider !== "meta_cloud") {
    return NextResponse.json(
      { error: "Template dispatch only supported for Meta Cloud channels" },
      { status: 400 },
    );
  }

  // 3. Lead e telefone utilizável.
  const { data: lead } = await supabase
    .from("leads")
    .select("id, phone, opt_out")
    .eq("id", leadId)
    .maybeSingle();
  if (!lead) {
    return NextResponse.json({ error: "Lead not found" }, { status: 404 });
  }
  const telefone = telefoneWhatsapp(lead.phone as string | null);
  if (!telefone) {
    return NextResponse.json({ error: "Lead sem telefone" }, { status: 400 });
  }

  // 4. Bloqueio / opt-out: o mesmo guard do send-template, antes de qualquer envio.
  if (await isLeadBlocked(supabase, lead.id, lead.opt_out as boolean | null)) {
    return NextResponse.json({ error: MENSAGEM_LEAD_BLOQUEADO }, { status: 403 });
  }

  // 5. Conversa do par lead+número: usa a existente ou cria (como o
  // get_or_create_conversation do backend: secretaria, active, sem agent_profile_id).
  const { data: existente, error: erroExistente } = await supabase
    .from("conversations")
    .select("id, status, stage")
    .eq("lead_id", lead.id)
    .eq("channel_id", channel.id)
    .limit(1)
    .maybeSingle();
  if (erroExistente) {
    // Sem saber se a conversa existe, criar outra poderia duplicar o par.
    return NextResponse.json({ error: erroExistente.message }, { status: 500 });
  }
  if (existente?.status === "blocked") {
    return NextResponse.json({ error: MENSAGEM_LEAD_BLOQUEADO }, { status: 403 });
  }

  let conversationId: string;
  let criada = false;
  if (existente) {
    conversationId = existente.id as string;
  } else {
    const { data: nova, error } = await supabase
      .from("conversations")
      .insert({ lead_id: lead.id, channel_id: channel.id, stage: "secretaria", status: "active" })
      .select("id, stage")
      .single();
    if (error || !nova) {
      return NextResponse.json({ error: error?.message ?? "Falha ao criar a conversa" }, { status: 500 });
    }
    conversationId = nova.id as string;
    criada = true;
  }

  // 6. Envio pela Meta.
  const providerConfig = channel.provider_config as Record<string, string>;
  let sentWamid: string | null;
  try {
    sentWamid = wamidDaResposta(
      await sendTemplateViaMeta(
        providerConfig,
        telefone,
        template_name,
        String(template_language_code),
        (template_variables as Record<string, string> | null | undefined) ?? null,
      ),
    );
  } catch (e: unknown) {
    if (!(e instanceof MetaRecusou)) {
      // Rede, timeout ou JSON inválido: a Meta pode ter aceitado. Não desfaz nada.
      return NextResponse.json(
        {
          error: "Não deu para confirmar o envio. Confira a conversa antes de tentar de novo.",
          conversation_id: conversationId,
        },
        { status: 502 },
      );
    }
    // 7. Meta recusou: desfaz só a conversa criada nesta requisição, e só se ainda
    // estiver intocada (sem mensagens, active, sem last_msg_at — checado no próprio delete).
    if (criada) {
      const { count, error: countError } = await supabase
        .from("messages")
        .select("id", { count: "exact", head: true })
        .eq("conversation_id", conversationId);
      if (!countError && count === 0) {
        await supabase
          .from("conversations")
          .delete()
          .eq("id", conversationId)
          .eq("status", "active")
          .is("last_msg_at", null);
      }
    }
    return NextResponse.json({ error: e.message }, { status: 502 });
  }

  await registrarTemplateEnviado(supabase, {
    conversationId,
    leadId: lead.id as string,
    channel: { id: channel.id as string, provider_config: providerConfig },
    templateName: template_name,
    templateLanguageCode: String(template_language_code),
    templateBody: template_body,
    sentWamid,
  });

  return NextResponse.json({ conversation_id: conversationId });
}

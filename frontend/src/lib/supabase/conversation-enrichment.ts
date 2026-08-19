import type { getServiceSupabase } from "@/lib/supabase/api";

type ServiceSupabase = Awaited<ReturnType<typeof getServiceSupabase>>;

const LEAD_FIELDS =
  "id, phone, name, company, stage, status, last_customer_message_at, ai_enabled, created_at, channel, on_hold, cnpj, razao_social, nome_fantasia, inscricao_estadual, endereco, telefone_comercial, email, instagram, traffic_type, utm_source";

const CHANNEL_FIELDS =
  "id, name, phone, provider, agent_profile_id, mode, agent_profiles(id, name, prompt_key)";

/**
 * Select das conversas com os joins que a lista precisa. Uma definição só para
 * a listagem, a busca de contatos e o fetch avulso — se divergirem, a conversa
 * aberta pela busca renderiza sem badge/janela e parece um bug de UI.
 *
 * @param innerLead força INNER JOIN em `leads`, exigido para filtrar a conversa
 *        por campos do lead (nome/telefone). Com o LEFT JOIN padrão o filtro
 *        apenas esvazia o objeto embutido, sem descartar a linha-pai.
 */
export function conversationSelect({ innerLead = false } = {}): string {
  const leadJoin = innerLead ? "leads!inner" : "leads";
  return [
    "*",
    "first_seller_response_at",
    "last_seller_response_at",
    `${leadJoin}(${LEAD_FIELDS})`,
    `channels(${CHANNEL_FIELDS})`,
    "agent_profiles(id, name, prompt_key)",
  ].join(", ");
}

const DISPATCH_SENT_BY = ["broadcast", "campaign", "automation", "followup", "cadence"];

/**
 * Conversa crua vinda do PostgREST — os joins chegam como objetos aninhados.
 *
 * O select é montado em runtime por {@link conversationSelect}, então o
 * supabase-js não consegue inferir a forma da linha (a inferência dele exige
 * string literal). Este tipo declara o contrato que as rotas de fato usam.
 */
export type EnrichableConversation = Record<string, unknown> & {
  id: string;
  channel_id: string;
  last_msg_at?: string | null;
  created_at?: string | null;
  leads?: { id?: string; phone?: string } | null;
  channels?: { provider?: string } | null;
};

/**
 * Anexa às conversas o preview da última mensagem e o card ativo do lead
 * (funil + etapa), que não saem no select por virem de RPCs.
 *
 * Fail-soft: erro de RPC deixa os campos nulos em vez de derrubar a resposta —
 * a conversa sem badge ainda é utilizável; a lista sumida, não.
 */
export async function enrichConversations<T extends EnrichableConversation>(
  supabase: ServiceSupabase,
  rows: T[],
): Promise<T[]> {
  if (rows.length === 0) return rows;

  const metaConvIds = rows
    .filter((c) => (c.channels as { provider?: string } | null)?.provider === "meta_cloud")
    .map((c) => c.id);

  const lastMsgMap = new Map<string, string>();
  const lastDirMap = new Map<string, "inbound" | "outbound">();
  if (metaConvIds.length > 0) {
    const { data: lastMsgs } = await supabase.rpc("get_last_messages", {
      conv_ids: metaConvIds,
    });
    for (const row of lastMsgs || []) {
      let prefix = "";
      if (row.sent_by === "seller") prefix = "Vendedor: ";
      else if (DISPATCH_SENT_BY.includes(row.sent_by)) prefix = "Disparo: ";
      else if (row.role === "assistant") prefix = "IA: ";
      lastMsgMap.set(row.conversation_id, prefix + row.content);
      // role "user" = lead falou por último → inbound; caso contrário nós falamos → outbound
      lastDirMap.set(row.conversation_id, row.role === "user" ? "inbound" : "outbound");
    }
  }

  const leadIds = rows
    .map((c) => (c.leads as { id?: string } | null)?.id)
    .filter(Boolean) as string[];

  type DealInfo = { pipeline_name: string; stage_label: string; stage_dot_color: string };
  const dealMap = new Map<string, DealInfo>();
  if (leadIds.length > 0) {
    const { data: dealRows } = await supabase.rpc("get_lead_deals", { lead_ids: leadIds });
    for (const row of dealRows || []) {
      dealMap.set(row.lead_id, {
        pipeline_name: row.pipeline_name,
        stage_label: row.stage_label,
        stage_dot_color: row.stage_dot_color,
      });
    }
  }

  return rows.map((c) => {
    const leadId = (c.leads as { id?: string } | null)?.id ?? "";
    const deal = dealMap.get(leadId);
    return {
      ...c,
      last_message_text: lastMsgMap.get(c.id) ?? null,
      last_message_direction: lastDirMap.get(c.id) ?? null,
      deal_pipeline_name: deal?.pipeline_name ?? null,
      deal_stage_label: deal?.stage_label ?? null,
      deal_stage_dot_color: deal?.stage_dot_color ?? null,
    };
  });
}

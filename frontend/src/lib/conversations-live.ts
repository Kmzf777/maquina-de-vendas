/**
 * Helpers puros para manter a lista de conversas viva a partir dos eventos
 * Realtime, SEM refetch integral do /api/conversations a cada evento.
 *
 * Contexto (corte de Egress): cada refetch da lista devolve TODAS as conversas
 * com lead completo + joins (~1,5-2,5MB) e era disparado a cada UPDATE de
 * `conversations` — que acontece a cada mensagem do sistema, em cada aba
 * aberta. O payload do próprio evento Realtime já traz a linha nova da tabela;
 * estes helpers aplicam esse delta localmente e reservam o refetch integral
 * para o que o delta não cobre (conversa nova/desconhecida).
 */

import type { Conversation } from "@/lib/types";

/** Colunas escalares da linha de `conversations` vindas no payload Realtime. */
export type ConversationRow = Partial<Conversation> & { id: string };

export interface MergeOverrides {
  /** Conversa marcada como lida localmente há <30s — payload atrasado não pode ressuscitar o badge. */
  forceUnreadZero?: boolean;
  /** Toggle de follow-up em voo — o valor otimista vence o payload até o PATCH confirmar. */
  pendingFollowup?: boolean;
}

/**
 * Aplica a linha do evento Realtime sobre a conversa existente, preservando o
 * que o payload NÃO carrega: joins (`leads`, `channels`, `agent_profiles`) e
 * campos computados pela API (`last_message_text`, `last_message_direction`,
 * `deal_*`). Sem essa preservação, um spread ingênuo apagaria o lead da UI.
 */
export function mergeConversationRow(
  existing: Conversation,
  row: ConversationRow,
  overrides: MergeOverrides = {},
): Conversation {
  const merged: Conversation = {
    ...existing,
    ...row,
    // Joins e campos computados não existem na linha crua — manter os atuais.
    leads: existing.leads,
    channels: existing.channels,
    agent_profiles: existing.agent_profiles,
    last_message_text: existing.last_message_text,
    last_message_direction: existing.last_message_direction,
    deal_pipeline_name: existing.deal_pipeline_name,
    deal_stage_label: existing.deal_stage_label,
    deal_stage_dot_color: existing.deal_stage_dot_color,
  };
  if (overrides.forceUnreadZero) merged.unread_count = 0;
  if (overrides.pendingFollowup !== undefined) merged.followup_enabled = overrides.pendingFollowup;
  return merged;
}

/** Mesma ordenação do /api/conversations: `last_msg_at desc`, nulls por último. */
export function sortByLastMsgDesc(list: Conversation[]): Conversation[] {
  return [...list].sort((a, b) => {
    if (!a.last_msg_at && !b.last_msg_at) return 0;
    if (!a.last_msg_at) return 1;
    if (!b.last_msg_at) return -1;
    return a.last_msg_at < b.last_msg_at ? 1 : a.last_msg_at > b.last_msg_at ? -1 : 0;
  });
}

const DISPATCH_SENT_BY = new Set(["broadcast", "campaign", "automation", "followup", "cadence"]);

export interface MessagePreview {
  text: string;
  direction: "inbound" | "outbound";
}

/**
 * Preview da última mensagem a partir do INSERT de `messages` — réplica exata
 * da montagem server-side do /api/conversations (prefixos "Vendedor: ",
 * "Disparo: ", "IA: "; role `user` = inbound). A RPC `get_last_messages` não
 * filtra roles: a última mensagem vence, seja ela qual for.
 */
export function previewFromMessage(msg: {
  role?: string | null;
  sent_by?: string | null;
  content?: string | null;
}): MessagePreview {
  let prefix = "";
  if (msg.sent_by === "seller") prefix = "Vendedor: ";
  else if (msg.sent_by && DISPATCH_SENT_BY.has(msg.sent_by)) prefix = "Disparo: ";
  else if (msg.role === "assistant") prefix = "IA: ";
  return {
    text: prefix + (msg.content ?? ""),
    direction: msg.role === "user" ? "inbound" : "outbound",
  };
}

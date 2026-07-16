import type { Campaign } from "@/lib/types";

/** Contagem de nós de uma campanha em qualquer shape de resposta:
 *  detalhe embute `nodes` completos (autoridade quando presente); a listagem traz o
 *  agregado `nodes_count` (embed campaign_nodes(count)); payloads antigos/realtime
 *  sem nenhum dos dois caem em 0. */
export function campaignNodeCount(campaign: Pick<Campaign, "nodes" | "nodes_count">): number {
  if (Array.isArray(campaign.nodes)) return campaign.nodes.length;
  return campaign.nodes_count ?? 0;
}

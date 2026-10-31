import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * O lead tem conversa que o /conversas consegue abrir? Mesma regra da listagem
 * (`/api/conversations`): conversa bloqueada não aparece. Usado pelo painel do
 * /trafego para desabilitar "Abrir conversa" (cartão 70d844a6). A rota do painel é
 * admin-only, e admin vê todos os canais, então não há filtro de canal aqui.
 *
 * null = não deu para saber (erro): quem chama trata como "pode ter".
 */
export async function leadTemConversa(sb: SupabaseClient, leadId: string): Promise<boolean | null> {
  try {
    const { count, error } = await sb
      .from("conversations")
      .select("id", { count: "exact", head: true })
      .eq("lead_id", leadId)
      .neq("status", "blocked");
    if (error) return null;
    return (count ?? 0) > 0;
  } catch {
    return null;
  }
}

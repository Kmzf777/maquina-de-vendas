import type { SupabaseClient } from "@supabase/supabase-js";
import { phoneVariantsBR } from "@/lib/phone";

export type LeadPorTelefone = { id: string; name: string | null; phone: string };

/**
 * Lead que já usa o número em qualquer formato antigo (cartão b747da43).
 * `canonical` é a saída de `normalizePhoneBR`; `excludeId` ignora o próprio
 * lead (edição). Havendo mais de um, devolve o mais antigo.
 */
export async function findLeadByPhoneVariants(
  supabase: SupabaseClient,
  canonical: string,
  excludeId?: string,
): Promise<LeadPorTelefone | null> {
  let q = supabase.from("leads").select("id, name, phone").in("phone", phoneVariantsBR(canonical));
  if (excludeId) q = q.neq("id", excludeId);
  const { data } = await q.order("created_at", { ascending: true }).limit(1);
  return ((data as LeadPorTelefone[] | null) ?? [])[0] ?? null;
}

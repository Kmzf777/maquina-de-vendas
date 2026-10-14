import type { SupabaseClient } from "@supabase/supabase-js";
import { normalizePhoneBR, phoneVariantsBR } from "@/lib/phone";

export type LeadPorTelefone = { id: string; name: string | null; phone: string };

/** Canônicos por consulta em lote: 4 formas cada, para a URL do PostgREST não estourar. */
const LOTE_CANONICOS = 100;

/**
 * Lead que já usa o número em qualquer formato antigo (cartão b747da43).
 * `canonical` é a saída de `normalizePhoneBR`; `excludeId` ignora o próprio
 * lead (edição). Havendo mais de um, devolve o mais antigo. Erro na consulta
 * lança: "não sei" não pode virar "não existe" e liberar um insert duplicado.
 */
export async function findLeadByPhoneVariants(
  supabase: SupabaseClient,
  canonical: string,
  excludeId?: string,
): Promise<LeadPorTelefone | null> {
  let q = supabase.from("leads").select("id, name, phone").in("phone", phoneVariantsBR(canonical));
  if (excludeId) q = q.neq("id", excludeId);
  const { data, error } = await q.order("created_at", { ascending: true }).limit(1);
  if (error) throw new Error(`Busca de lead por telefone falhou: ${error.message}`);
  return ((data as LeadPorTelefone[] | null) ?? [])[0] ?? null;
}

/**
 * Versão em lote (importação): para cada canônico, o lead mais antigo que usa o
 * número em qualquer formato. A chave do mapa é o canônico; `phone` do valor é o
 * que está gravado de fato (use-o para atualizar o lead).
 */
export async function findLeadsByPhoneVariants(
  supabase: SupabaseClient,
  canonicals: string[],
): Promise<Map<string, LeadPorTelefone>> {
  const mapa = new Map<string, LeadPorTelefone>();
  for (let i = 0; i < canonicals.length; i += LOTE_CANONICOS) {
    const variantes = canonicals.slice(i, i + LOTE_CANONICOS).flatMap(phoneVariantsBR);
    const { data, error } = await supabase
      .from("leads")
      .select("id, name, phone")
      .in("phone", variantes)
      .order("created_at", { ascending: true });
    if (error) throw new Error(`Busca de leads por telefone falhou: ${error.message}`);
    for (const lead of (data as LeadPorTelefone[] | null) ?? []) {
      const canonico = normalizePhoneBR(lead.phone);
      if (canonico && !mapa.has(canonico)) mapa.set(canonico, lead);
    }
  }
  return mapa;
}

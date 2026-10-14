/**
 * Endereço estruturado do lead (cartão b3788533).
 *
 * As colunas `cep, logradouro, numero, complemento, bairro, municipio, uf` de
 * `leads` são a fonte do endereço que vai para o contato no Bling; o texto
 * livre `leads.endereco` (legado) passa a ser regravado com `formatAddress`.
 * "Completo" aqui é o mesmo mínimo que o Bling aceita: CEP de 8 dígitos, rua,
 * número, cidade e uma das 27 UFs.
 */
import { UFS, cepDigits } from "@/lib/bling-contact-form";

export const ADDRESS_FIELDS = ["cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf"] as const;
export type AddressField = (typeof ADDRESS_FIELDS)[number];
export type LeadAddress = Partial<Record<AddressField, string | null>>;

const t = (v: string | null | undefined) => (v ?? "").trim();

export function isAddressComplete(a: LeadAddress): boolean {
  return cepDigits(a.cep).length === 8 && !!t(a.logradouro) && !!t(a.numero)
    && !!t(a.municipio) && (UFS as readonly string[]).includes(t(a.uf).toUpperCase());
}

export function hasAddressChange(body: Record<string, unknown>): boolean {
  return ADDRESS_FIELDS.some((f) => f in body);
}

/** "Rua X, 123, Sala 2 - Bairro - Cidade/UF 38400-100" (vazios somem). */
export function formatAddress(a: LeadAddress): string | null {
  const cep = cepDigits(a.cep);
  const rua = [t(a.logradouro), t(a.numero), t(a.complemento)].filter(Boolean).join(", ");
  const cidade = [t(a.municipio), t(a.uf).toUpperCase()].filter(Boolean).join("/");
  const cepFmt = cep.length === 8 ? `${cep.slice(0, 5)}-${cep.slice(5)}` : cep;
  const s = [rua, t(a.bairro), [cidade, cepFmt].filter(Boolean).join(" ")].filter(Boolean).join(" - ");
  return s || null;
}

/** Resposta do ViaCEP → campos do lead; `null` se erro/CEP inexistente. */
export function fromViaCep(json: unknown): LeadAddress | null {
  if (!json || typeof json !== "object" || (json as { erro?: unknown }).erro) return null;
  const j = json as Record<string, string>;
  return { logradouro: j.logradouro || "", bairro: j.bairro || "", municipio: j.localidade || "", uf: j.uf || "" };
}

/** Preenche só os campos vazios (não pisa no que o vendedor digitou). */
export function mergeViaCep(atual: LeadAddress, via: LeadAddress): LeadAddress {
  const out = { ...atual };
  for (const [k, v] of Object.entries(via) as [AddressField, string][]) if (!t(out[k]) && v) out[k] = v;
  return out;
}

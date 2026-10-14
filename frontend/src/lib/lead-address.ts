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

/** `bling_endereco` devolvido pelo PATCH /api/leads/[id]. */
export interface BlingEnderecoResultado {
  status: string;
  message?: string;
  contas?: { account: string; contact_id?: number; status: string; message?: string }[];
}

/** Contas que falharam, como "conta: motivo; conta2: motivo2". */
function falhas(r: BlingEnderecoResultado): string {
  return (r.contas ?? [])
    .filter((c) => c.status === "error")
    .map((c) => (c.message ? `${c.account}: ${c.message}` : c.account))
    .join("; ");
}

/** Linha mostrada na ficha depois de salvar o endereço; `null` = nada a mostrar. */
export function mensagemBlingEndereco(
  r: BlingEnderecoResultado | null | undefined,
): { texto: string; erro: boolean } | null {
  switch (r?.status) {
    case "updated":
      return { texto: "Endereço atualizado no Bling", erro: false };
    case "partial":
      return { texto: `Endereço atualizado em parte do Bling: ${falhas(r)}`, erro: true };
    case "error":
      return { texto: `Falha ao atualizar no Bling: ${r.message || falhas(r) || "erro desconhecido"}`, erro: true };
    case "incomplete":
      return { texto: "Endereço incompleto — não enviado ao Bling", erro: false };
    case "not_linked":
      return { texto: "Lead sem contato no Bling — endereço salvo só no CRM", erro: false };
    default:
      return null;
  }
}

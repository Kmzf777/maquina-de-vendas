/** Derivações de exibição do contato do Bling vinculado a um lead. */

/**
 * O deep-link do CONTATO não está documentado no OpenAPI do Bling. O padrão do
 * pedido (`BLING_ORDER_URL_TEMPLATE` em `sale-display.ts`) já foi confirmado
 * abrindo um pedido real; este segue a mesma forma por analogia, mas não foi
 * confirmado abrindo um contato real — confira e ajuste esta constante se
 * estiver errada, é o único lugar do código que precisa mudar.
 */
export const BLING_CONTACT_URL_TEMPLATE =
  "https://www.bling.com.br/contatos.php#edit/{id}";

export function blingContactUrl(contactId: number | null | undefined): string {
  return contactId ? BLING_CONTACT_URL_TEMPLATE.replace("{id}", String(contactId)) : "";
}

/**
 * Forma como `bling_contacts.endereco` chega do espelho: o objeto bruto
 * `endereco.geral` da API do Bling (ver `backend/app/bling/sync.py:map_contact`),
 * não uma string pronta.
 */
export interface BlingAddress {
  endereco?: string | null;
  numero?: string | null;
  complemento?: string | null;
  bairro?: string | null;
  cep?: string | null;
  municipio?: string | null;
  uf?: string | null;
}

/** Formata o endereço do contato (objeto do espelho) numa linha legível. */
export function formatBlingAddress(
  endereco: BlingAddress | string | null | undefined
): string {
  if (!endereco) return "";
  if (typeof endereco === "string") return endereco;
  const rua = [endereco.endereco, endereco.numero].filter(Boolean).join(", ");
  const cidadeUf =
    endereco.municipio && endereco.uf
      ? `${endereco.municipio}/${endereco.uf}`
      : endereco.municipio || endereco.uf || "";
  return [rua, endereco.bairro, cidadeUf, endereco.cep].filter(Boolean).join(" - ");
}

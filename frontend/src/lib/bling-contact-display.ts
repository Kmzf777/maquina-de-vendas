/** Derivações de exibição do contato do Bling vinculado a um lead. */
import type { ContaBling } from "@/lib/bling-accounts";

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
 * Rotulo da conta Bling de um contato vinculado, ou null quando nao ha o que
 * dizer. Mesma razao de existir que `accountLabel` em `sale-display.ts`: o
 * Bling nao tem URL que force a conta — `blingContactUrl` abre no painel de
 * onde o usuario ja estiver logado, e um contato da conta 2 aberto por quem
 * esta logado na conta 1 mostra "nao encontrado". O rotulo avisa em qual
 * painel entrar ANTES do clique, ja que o link sozinho nao resolve isso.
 *
 * Recebe o slug direto (nao um objeto Sale/contato): o vinculo lead-contato
 * (`lead_bling_contacts`) e o contato em si vivem em modulos diferentes, e este
 * lib nao tem por que importar um tipo de componente so para nomear um campo.
 *
 * Devolve null com uma conta so: sem ambiguidade a desfazer, um rotulo fixo
 * seria ruido.
 */
export function accountLabel(
  account: string | null | undefined, contas: ContaBling[],
): string | null {
  if (!account) return null;           // contato sem conta conhecida
  if (contas.length <= 1) return null; // sem ambiguidade
  const conta = contas.find((c) => c.account === account);
  // Conta removida do BLING_ACCOUNTS depois do vinculo: o slug cru diz mais
  // que esconder a informacao, e nao quebra a tela.
  return conta?.label ?? account;
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

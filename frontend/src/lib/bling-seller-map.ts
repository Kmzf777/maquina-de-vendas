/**
 * Indice em memoria do vinculo usuario do CRM -> vendedor do Bling.
 *
 * Existe porque a chave e COMPOSTA: `bling_seller_map` tem PK
 * `(user_email, account)` desde 20260913_bling_multi_conta.sql, e o Bling
 * identifica vendedor por id proprio de cada CNPJ — a mesma pessoa tem um id
 * em cada conta. Indexar so pelo e-mail colapsaria as duas linhas em uma e a
 * tela passaria a exibir o vendedor da conta errada.
 *
 * Logica pura, fora do componente, pelo mesmo motivo de `bling-accounts.ts`.
 */
export type VinculoVendedor = {
  user_email: string;
  account: string;
  bling_seller_id: number;
};

/** Chave composta serializada. `Record` em vez de `Map` para o estado do React. */
export type MapaVendedores = Record<string, number>;

function chave(account: string, email: string): string {
  return `${account} ${email}`;
}

export function indexarVinculos(linhas: VinculoVendedor[]): MapaVendedores {
  const mapa: MapaVendedores = {};
  for (const linha of linhas) {
    mapa[chave(linha.account, linha.user_email)] = linha.bling_seller_id;
  }
  return mapa;
}

/**
 * Novo mapa com UMA celula trocada. `null` remove a entrada em vez de guardar
 * null: `bling_seller_id` e NOT NULL na tabela, entao desvincular apaga a linha
 * — e o estado local precisa refletir isso, nao guardar um buraco.
 */
export function comVinculo(
  mapa: MapaVendedores,
  account: string,
  email: string,
  sellerId: number | null,
): MapaVendedores {
  const copia = { ...mapa };
  if (sellerId === null) {
    delete copia[chave(account, email)];
  } else {
    copia[chave(account, email)] = sellerId;
  }
  return copia;
}

export function vinculoDe(
  mapa: MapaVendedores,
  account: string,
  email: string,
): number | null {
  const id = mapa[chave(account, email)];
  return id ?? null;
}

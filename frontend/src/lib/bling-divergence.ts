/** Registro de divergencia entre o que o CRM guarda e o que o Bling aceitou. */
export interface Divergence {
  fields: string[];
  bling: Record<string, unknown>;
  crm: Record<string, unknown>;
  at: string;
}

/**
 * So recusa de VALIDACAO (422) vira divergencia. 202 e 5xx sao transitorios: o
 * pedido nao foi recusado, so nao foi entregue ainda — marcar divergencia neles
 * transformaria instabilidade de rede em ruido permanente no relatorio.
 */
export function shouldMarkDivergent(status: number): boolean {
  return status === 422;
}

export function divergenceFrom(
  bling: Record<string, unknown>,
  crm: Record<string, unknown>,
  at: string
): Divergence {
  const fields = Object.keys(crm).filter((k) => crm[k] !== bling[k]);
  return {
    fields,
    bling: Object.fromEntries(fields.map((k) => [k, bling[k]])),
    crm: Object.fromEntries(fields.map((k) => [k, crm[k]])),
    at,
  };
}

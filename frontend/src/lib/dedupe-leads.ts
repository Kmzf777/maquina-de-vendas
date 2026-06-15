/**
 * Remove telefones repetidos dentro do mesmo lote de importação, mantendo a
 * primeira ocorrência. Necessário porque o insert em lote em `leads` viola a
 * constraint única `leads_phone_key` se o CSV trouxer o mesmo telefone duas
 * vezes — o que derruba a importação inteira (HTTP 500) antes de inserir.
 */
export function dedupeByPhone<T extends { phone: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.phone)) return false;
    seen.add(item.phone);
    return true;
  });
}

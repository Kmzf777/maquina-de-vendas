/**
 * Colapsa templates duplicados por (name, language) na listagem global.
 *
 * Por quê: `message_templates` é escopado por `channel_id`, mas os 3 canais Meta do
 * projeto compartilham a MESMA WABA (templates da Meta são por-WABA, não por número).
 * O sync por canal cria, então, uma linha-espelho por canal do mesmo template — e a
 * listagem global (`GET /api/templates` sem channel_id) exibe o mesmo nome 2-3x.
 * Funcionalmente, todo consumo de template resolve por NOME (channel-agnóstico), então
 * uma linha por (name, language) basta para exibição. Esta dedupe é de APRESENTAÇÃO:
 * não toca no banco, não altera o modelo por-canal, é reversível.
 *
 * Mantém a primeira ocorrência por (name, language), preferindo uma linha NÃO cancelada
 * (uma cópia cancelada não deve esconder a aprovada equivalente). Ordem estável.
 */
export function dedupeTemplatesByNameLang<
  T extends { name: string; language: string; status?: string | null }
>(rows: T[]): T[] {
  const chosenIndex = new Map<string, number>();
  const result: T[] = [];

  for (const row of rows) {
    const key = `${row.name}::${row.language}`;
    const existingIdx = chosenIndex.get(key);

    if (existingIdx === undefined) {
      chosenIndex.set(key, result.length);
      result.push(row);
      continue;
    }

    // Já temos uma linha para este (name, language). Só troca se a atual for
    // não-cancelada E a guardada for cancelada (promove a aprovada).
    const kept = result[existingIdx];
    const keptCancelled = (kept.status ?? "").toLowerCase() === "cancelled";
    const rowCancelled = (row.status ?? "").toLowerCase() === "cancelled";
    if (keptCancelled && !rowCancelled) {
      result[existingIdx] = row;
    }
  }

  return result;
}

/**
 * Texto da recusa do Bling para o vendedor.
 *
 * `message`/`detail` do Bling são genéricos ("O contato não pode ser salvo pois
 * ocorreram problemas com sua validação") e não dizem o que corrigir. O motivo
 * real vem campo a campo em `fields` (`[{campo, mensagem}]`, montado no backend
 * a partir de `error.fields`). Quando existe, é ele que aparece; sem ele, o
 * comportamento antigo (`message` + `detail`) continua.
 *
 * O texto usa quebra de linha — quem exibe precisa de `whitespace-pre-line`.
 */

const texto = (v: unknown): string | null =>
  typeof v === "string" && v.trim() ? v.trim() : null;

export function blingErrorReasons(body: unknown): string[] {
  const fields = (body as { fields?: unknown } | null | undefined)?.fields;
  if (!Array.isArray(fields)) return [];
  const linhas: string[] = [];
  for (const f of fields) {
    if (!f || typeof f !== "object") continue;
    const mensagem = texto((f as { mensagem?: unknown }).mensagem);
    if (!mensagem) continue;
    const campo = texto((f as { campo?: unknown }).campo);
    linhas.push(campo ? `${campo}: ${mensagem}` : mensagem);
  }
  return linhas;
}

export function blingErrorMessage(body: unknown, fallback: string): string {
  const motivos = blingErrorReasons(body);
  if (motivos.length > 0) {
    return ["O Bling recusou:", ...motivos.map((m) => `• ${m}`)].join("\n");
  }
  const b = (body ?? {}) as { message?: unknown; detail?: unknown };
  return [texto(b.message), texto(b.detail)].filter(Boolean).join(" ") || fallback;
}

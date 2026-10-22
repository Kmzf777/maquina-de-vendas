/**
 * `deals.assigned_to` (e `leads.assigned_to`) guardam o uuid de `public.vendedores`
 * (cartão b67f1c6b). Nome digitado à mão não é mais aceito: a FK recusaria com um
 * erro genérico; aqui vira um 400 legível.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ValidacaoVendedorId =
  | { ok: true; value: string | null }
  | { ok: false; error: string };

export function validarVendedorId(v: unknown): ValidacaoVendedorId {
  if (v === null || v === undefined) return { ok: true, value: null };
  if (typeof v !== "string") return { ok: false, error: "assigned_to deve ser o id de um vendedor." };
  const s = v.trim();
  if (!s) return { ok: true, value: null };
  if (!UUID_RE.test(s)) return { ok: false, error: "assigned_to deve ser o id de um vendedor (escolha na lista)." };
  return { ok: true, value: s.toLowerCase() };
}

/** Código Postgres de FK violada: o uuid não está em `vendedores`. */
export const FK_VIOLATION = "23503";

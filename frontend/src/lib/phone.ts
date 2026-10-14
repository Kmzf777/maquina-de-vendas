/**
 * Normalizes a Brazilian phone number to E.164-without-"+" (55 + DDD + 9 digits).
 *
 * Mirrors `backend/app/leads/service.py` `normalize_phone`: it injects the
 * Brazilian mobile 9th digit when the number is missing it, so frontend-created
 * leads (e.g. CSV import) match the canonical 13-digit phone the inbound
 * WhatsApp webhook creates. Without this parity, leads end up duplicated and
 * conversations get fragmented across the 12-digit and 13-digit rows.
 *
 * Returns null when the input cannot be normalized to a valid 13-digit
 * `55` + DDD + 9-digit number.
 */
export function normalizePhoneBR(raw: string): string | null {
  let digits = raw.replace(/\D/g, "");
  if (!digits) return null;
  if (digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length === 10 || digits.length === 11) digits = "55" + digits;
  if ((digits.length === 12 || digits.length === 13) && !digits.startsWith("55")) return null;
  if (digits.length === 12 && digits.startsWith("55")) {
    digits = digits.slice(0, 4) + "9" + digits.slice(4);
  }
  return digits.length === 13 && digits.startsWith("55") ? digits : null;
}

/**
 * Formas em que um telefone canônico (saída de `normalizePhoneBR`) já foi gravado
 * em `leads.phone` antes de existir normalização: sem o 9, sem o 55, sem os dois.
 * Usado para achar o lead existente antes de criar outro (cartão b747da43).
 */
export function phoneVariantsBR(canonical: string): string[] {
  if (!/^55\d{2}9\d{8}$/.test(canonical)) return [canonical];
  const semNove = canonical.slice(0, 4) + canonical.slice(5);
  return [canonical, semNove, canonical.slice(2), semNove.slice(2)];
}

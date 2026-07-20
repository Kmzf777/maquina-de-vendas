/** Lowercases and strips diacritics (á→a, ç→c, ã→a) for accent-insensitive matching. */
export function foldText(value: string): string {
  return value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export interface LeadSearchFields {
  name?: string | null;
  phone?: string | null;
  company?: string | null;
  razao_social?: string | null;
  nome_fantasia?: string | null;
}

/**
 * True when `query` matches the lead by name/company/razao_social/nome_fantasia
 * (accent-insensitive substring) OR by phone (digit-substring, so formatted input
 * like "(34) 99999-8888" matches the stored 13-digit "5534999998888").
 * Empty/whitespace query matches everything.
 */
export function leadMatchesSearch(query: string, lead: LeadSearchFields): boolean {
  const raw = query.trim();
  if (!raw) return true;

  const q = foldText(raw);
  const textMatch = [lead.name, lead.company, lead.razao_social, lead.nome_fantasia].some(
    (field) => field != null && foldText(field).includes(q)
  );
  if (textMatch) return true;

  const qDigits = raw.replace(/\D/g, "");
  if (qDigits && lead.phone && lead.phone.replace(/\D/g, "").includes(qDigits)) return true;

  return false;
}

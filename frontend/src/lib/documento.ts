/**
 * Validação de CPF/CNPJ no cliente.
 *
 * Espelho EXATO de `_cpf_ok`/`_cnpj_ok`/`is_valid_document` em
 * `backend/app/bling/contacts.py`. O documento é a chave única que impede
 * duplicata de contato no Bling — validar o dígito verificador aqui evita que o
 * vendedor mande um número digitado errado, que não acharia o contato existente
 * e criaria um cadastro duplicado no ERP.
 *
 * Divergir do backend seria pior que não validar: o modal aceitaria um documento
 * que o `POST /api/bling/contacts` recusa com 422, ou recusaria um válido.
 */

/** Só os dígitos. String vazia (ou nula) vira `null`, como `doc_digits`. */
export function docDigits(value: string | null | undefined): string | null {
  if (!value) return null;
  const out = String(value).replace(/\D/g, "");
  return out || null;
}

function allSameDigit(d: string): boolean {
  return new Set(d).size === 1;
}

function cpfOk(d: string): boolean {
  if (allSameDigit(d)) return false;
  for (const tamanho of [9, 10]) {
    let soma = 0;
    for (let i = 0; i < tamanho; i++) {
      soma += Number(d[i]) * (tamanho + 1 - i);
    }
    const dv = ((soma * 10) % 11) % 10;
    if (dv !== Number(d[tamanho])) return false;
  }
  return true;
}

function cnpjOk(d: string): boolean {
  if (allSameDigit(d)) return false;
  const pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const pesos2 = [6, ...pesos1];
  const rodadas: [number[], number][] = [
    [pesos1, 12],
    [pesos2, 13],
  ];
  for (const [pesos, pos] of rodadas) {
    let soma = 0;
    for (let i = 0; i < pos; i++) {
      soma += Number(d[i]) * pesos[i];
    }
    const resto = soma % 11;
    const dv = resto < 2 ? 0 : 11 - resto;
    if (dv !== Number(d[pos])) return false;
  }
  return true;
}

/** CPF (11 dígitos) ou CNPJ (14) com dígito verificador correto. */
export function isValidDocument(value: string | null | undefined): boolean {
  const d = docDigits(value);
  if (!d) return false;
  if (d.length === 11) return cpfOk(d);
  if (d.length === 14) return cnpjOk(d);
  return false;
}

/** "F" (pessoa física) ou "J", inferido pelo tamanho — como faz `create_contact`. */
export function documentKind(value: string | null | undefined): "F" | "J" {
  return (docDigits(value) ?? "").length === 14 ? "J" : "F";
}

/** Máscara de exibição: 000.000.000-00 / 00.000.000/0000-00. */
export function formatDocument(value: string | null | undefined): string {
  const d = docDigits(value) ?? "";
  if (d.length === 11) {
    return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
  }
  if (d.length === 14) {
    return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
  }
  return value ?? "";
}

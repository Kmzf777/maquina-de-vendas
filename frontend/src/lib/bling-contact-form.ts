/**
 * Montagem do cadastro de contato do Bling (fluxo do 409 "missing").
 *
 * Mesma razão do `bling-order-state.ts`: a suíte do frontend é de lógica pura,
 * então o que pode dar errado — validação do documento, formato aninhado do
 * endereço, campo de telefone certo — mora aqui e é testado; o componente só
 * renderiza.
 *
 * O corpo enviado espelha `ContactIn` de `backend/app/bling/router.py`
 * (`lead_id`, `nome`, `numeroDocumento`, `tipo`, `email`, `telefone`, `celular`,
 * `endereco`) e o endereço usa o formato `{geral: {...}}` que `map_contact`
 * espera ao espelhar o contato de volta.
 */
import { docDigits, documentKind, isValidDocument } from "@/lib/documento";

export interface ContactForm {
  nome: string;
  documento: string;
  email: string;
  telefone: string;
  cep: string;
  logradouro: string;
  numero: string;
  bairro: string;
  municipio: string;
  uf: string;
}

export interface ContactAddress {
  endereco: string;
  numero: string;
  bairro: string;
  cep: string;
  municipio: string;
  uf: string;
}

export interface ContactPayload {
  lead_id: string;
  nome: string;
  numeroDocumento: string;
  tipo: "F" | "J";
  email?: string;
  telefone?: string;
  celular?: string;
  endereco?: { geral: ContactAddress };
}

export interface ContactPayloadResult {
  valid: boolean;
  errors: { nome?: string; documento?: string };
  payload: ContactPayload;
}

export function blankContactForm(defaults: Partial<ContactForm> = {}): ContactForm {
  return {
    nome: "",
    documento: "",
    email: "",
    telefone: "",
    cep: "",
    logradouro: "",
    numero: "",
    bairro: "",
    municipio: "",
    uf: "",
    ...defaults,
  };
}

/**
 * Onde o número digitado entra no cadastro do Bling.
 *
 * 11 dígitos (DDD + 9 + 8) é celular; o resto vai como telefone fixo. O espelho
 * (`map_contact`) normaliza os dois campos e a busca por telefone consulta ambos,
 * então o que se ganha aqui é um cadastro que não mente sobre o tipo da linha.
 */
export function phoneField(raw: string | null | undefined): "celular" | "telefone" {
  return (docDigits(raw) ?? "").length >= 11 ? "celular" : "telefone";
}

function limpo(valor: string | null | undefined): string {
  return (valor ?? "").trim();
}

export function buildContactPayload(
  form: ContactForm,
  leadId: string,
): ContactPayloadResult {
  const nome = limpo(form.nome);
  const doc = docDigits(form.documento);
  const errors: ContactPayloadResult["errors"] = {};

  if (!nome) errors.nome = "Informe o nome do cliente";
  if (!doc) errors.documento = "O CPF/CNPJ é obrigatório";
  else if (!isValidDocument(doc)) errors.documento = "CPF/CNPJ inválido";

  const payload: ContactPayload = {
    lead_id: leadId,
    nome,
    numeroDocumento: doc ?? "",
    tipo: documentKind(doc),
  };

  const email = limpo(form.email);
  if (email) payload.email = email;

  const telefone = limpo(form.telefone);
  if (telefone) payload[phoneField(telefone)] = telefone;

  // O endereço é opcional; só viaja se o vendedor preencheu alguma coisa, senão
  // o Bling receberia um bloco de strings vazias e gravaria endereço em branco.
  const geral: ContactAddress = {
    endereco: limpo(form.logradouro),
    numero: limpo(form.numero),
    bairro: limpo(form.bairro),
    cep: limpo(form.cep),
    municipio: limpo(form.municipio),
    uf: limpo(form.uf).toUpperCase(),
  };
  if (Object.values(geral).some((v) => v)) payload.endereco = { geral };

  return { valid: Object.keys(errors).length === 0, errors, payload };
}

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
 *
 * ## Por que razão social, CPF/CNPJ e e-mail são todos obrigatórios
 *
 * O documento sempre foi: é a chave que impede contato duplicado no ERP. O
 * e-mail passou a ser por decisão de negócio da proposta comercial — o orçamento
 * é um documento que se entrega ao cliente, e um contato sem e-mail no Bling é
 * uma proposta que não tem para onde ir. Cadastrar agora e correr atrás do
 * e-mail depois é o caminho que produz base suja: o contato nasce incompleto,
 * ninguém volta para completar, e a falta só aparece na hora de enviar.
 *
 * A exigência vale para **toda** criação de contato, inclusive o registro de
 * venda que já está em produção — é decisão explícita do usuário (decisão 6 do
 * design do orçamento), não um efeito colateral. Duas regras diferentes para o
 * mesmo cadastro dariam contato completo ou incompleto conforme a porta de
 * entrada, que é exatamente o que se quer evitar.
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
  errors: { nome?: string; documento?: string; email?: string };
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

/**
 * Formato de e-mail: uma checagem sóbria, de propósito.
 *
 * Exige o mínimo que distingue um e-mail de um erro de digitação — algo antes de
 * um único `@`, e depois dele um domínio com pelo menos um ponto separando
 * rótulos não vazios. Nada de regex de RFC 5322: ela é enorme, ninguém a revisa,
 * e o erro que ela comete é o caro — recusar o e-mail real de um cliente e
 * travar o cadastro na frente do vendedor, que não tem como contornar.
 *
 * Aqui o custo dos dois erros é assimétrico. Deixar passar um endereço
 * sintaticamente exótico não quebra nada: quem valida de verdade é o Bling no
 * 422, e depois disso o próprio servidor de e-mail. Já um falso negativo impede
 * a venda. Por isso o `[^\s@]` é permissivo com acento, `+`, `_` e o que mais o
 * cliente tiver no endereço — só espaço e `@` extra são barrados.
 */
const EMAIL_RE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

export function buildContactPayload(
  form: ContactForm,
  leadId: string,
): ContactPayloadResult {
  const nome = limpo(form.nome);
  const doc = docDigits(form.documento);
  const email = limpo(form.email);
  const errors: ContactPayloadResult["errors"] = {};

  if (!nome) errors.nome = "Informe o nome do cliente";
  if (!doc) errors.documento = "O CPF/CNPJ é obrigatório";
  else if (!isValidDocument(doc)) errors.documento = "CPF/CNPJ inválido";
  if (!email) errors.email = "O e-mail é obrigatório";
  else if (!EMAIL_RE.test(email)) errors.email = "E-mail inválido";

  const payload: ContactPayload = {
    lead_id: leadId,
    nome,
    numeroDocumento: doc ?? "",
    tipo: documentKind(doc),
  };

  // Continua condicional mesmo sendo obrigatório: um formulário inválido não
  // chega a ser enviado, e mandar `email: ""` gravaria campo em branco no ERP.
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

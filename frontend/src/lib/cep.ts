/**
 * Busca de CEP no ViaCEP para o cadastro do contato no Bling.
 *
 * O Bling valida o município pelo nome do IBGE (com acento): "Sao Paulo" ou
 * "Frutal-MG" digitados à mão são recusados com uma frase genérica. O ViaCEP
 * devolve exatamente o nome do IBGE, então preencher a partir do CEP evita a
 * recusa mais comum.
 *
 * A consulta é conveniência, nunca bloqueio: falha, timeout ou CEP
 * inexistente devolvem `null` e o vendedor segue digitando à mão.
 *
 * O fetch sai direto do navegador: o app não define Content-Security-Policy
 * (nem `next.config.ts`, nem `src/proxy.ts`, nem o Traefik em produção) e o
 * ViaCEP responde com CORS aberto.
 */
import { cepDigits, type ContactForm } from "@/lib/bling-contact-form";

export interface EnderecoCep {
  logradouro: string;
  bairro: string;
  municipio: string;
  uf: string;
}

const texto = (v: unknown): string => (typeof v === "string" ? v.trim() : "");

export async function buscarCep(
  cep: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 4000,
): Promise<EnderecoCep | null> {
  const digitos = cepDigits(cep);
  if (digitos.length !== 8) return null;

  const controle = new AbortController();
  const timer = setTimeout(() => controle.abort(), timeoutMs);
  try {
    const res = await fetchImpl(`https://viacep.com.br/ws/${digitos}/json/`, {
      signal: controle.signal,
    });
    if (!res.ok) return null;
    const corpo = (await res.json()) as Record<string, unknown> | null;
    // O ViaCEP já devolveu `erro: true` e, na versão atual, `erro: "true"`.
    if (!corpo || corpo.erro === true || corpo.erro === "true") return null;
    const achado = {
      logradouro: texto(corpo.logradouro),
      bairro: texto(corpo.bairro),
      municipio: texto(corpo.localidade),
      uf: texto(corpo.uf).toUpperCase(),
    };
    return achado.municipio || achado.uf ? achado : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Completa o endereço com o que veio do CEP — só nos campos em branco. O que o
 * vendedor digitou é dele (pode saber melhor que a base dos Correios), e um
 * campo vazio na resposta (CEP geral de cidade pequena) não apaga nada.
 */
export function preencherEndereco(form: ContactForm, achado: EnderecoCep): ContactForm {
  const vazio = (v: string) => !v.trim();
  return {
    ...form,
    logradouro: vazio(form.logradouro) && achado.logradouro ? achado.logradouro : form.logradouro,
    bairro: vazio(form.bairro) && achado.bairro ? achado.bairro : form.bairro,
    municipio: vazio(form.municipio) && achado.municipio ? achado.municipio : form.municipio,
    uf: vazio(form.uf) && achado.uf ? achado.uf : form.uf,
  };
}

/**
 * A tela interativa que o bot mandou ao lead: botões de resposta, menu de lista ou
 * carrossel de imagens.
 *
 * Até 10/2026 o /conversas mostrava só o TEXTO das mensagens da ValerIA — o vendedor não
 * via que o lead tinha três botões na tela, nem o menu, nem os cards do carrossel. O
 * backend agora grava a estrutura enviada em `messages.metadata.interativo`
 * (backend/app/button_flow/interativo.py, que é a outra metade deste contrato):
 *
 *   {tipo: "botoes",    imagem: url|null, botoes: [rótulo, ...]}
 *   {tipo: "lista",     botao: rótulo, linhas: [{titulo, descricao}, ...]}
 *   {tipo: "carrossel", cards: [{imagem, texto, botoes: [rótulo, ...]}, ...]}
 *
 * `metadata` é jsonb: pode chegar escalar, array, null ou de uma versão futura. Tudo é
 * validado aqui; o que não reconhecemos vira `null` e a bolha desenha só o texto, como
 * antes — nunca uma tela inventada.
 */

export interface InterativoBotoes {
  tipo: "botoes";
  imagem: string | null;
  botoes: string[];
}

export interface InterativoLista {
  tipo: "lista";
  botao: string;
  linhas: { titulo: string; descricao: string }[];
}

export interface InterativoCard {
  imagem: string | null;
  texto: string;
  botoes: string[];
}

export interface InterativoCarrossel {
  tipo: "carrossel";
  cards: InterativoCard[];
}

export type Interativo = InterativoBotoes | InterativoLista | InterativoCarrossel;

/** Rótulo default do WhatsApp para o botão que abre a lista (= reg.ROTULO_BOTAO_LISTA). */
const ROTULO_LISTA_DEFAULT = "Ver opções";

type Obj = Record<string, unknown>;

function obj(valor: unknown): Obj | null {
  return valor && typeof valor === "object" && !Array.isArray(valor) ? (valor as Obj) : null;
}

function texto(valor: unknown): string {
  return typeof valor === "string" ? valor.trim() : "";
}

function rotulos(valor: unknown): string[] {
  return Array.isArray(valor) ? valor.map(texto).filter((r) => r.length > 0) : [];
}

/** Só URL http(s): é o que o backend grava (URL pública do Storage). */
function url(valor: unknown): string | null {
  const s = texto(valor);
  return /^https?:\/\//i.test(s) ? s : null;
}

function lerBotoes(raw: Obj): InterativoBotoes | null {
  const botoes = rotulos(raw.botoes);
  return botoes.length ? { tipo: "botoes", imagem: url(raw.imagem), botoes } : null;
}

function lerLista(raw: Obj): InterativoLista | null {
  const linhas = (Array.isArray(raw.linhas) ? raw.linhas : [])
    .map(obj)
    .filter((l): l is Obj => l !== null)
    .map((l) => ({ titulo: texto(l.titulo), descricao: texto(l.descricao) }))
    .filter((l) => l.titulo.length > 0);
  if (!linhas.length) return null;
  return { tipo: "lista", botao: texto(raw.botao) || ROTULO_LISTA_DEFAULT, linhas };
}

function lerCarrossel(raw: Obj): InterativoCarrossel | null {
  const cards = (Array.isArray(raw.cards) ? raw.cards : [])
    .map(obj)
    .filter((c): c is Obj => c !== null)
    .map((c) => ({
      imagem: url(c.imagem),
      // Sem trim: o texto do card é exibido com as quebras de linha como saiu.
      texto: typeof c.texto === "string" ? c.texto : "",
      botoes: rotulos(c.botoes),
    }))
    .filter((c) => c.imagem !== null || c.texto.trim().length > 0);
  return cards.length ? { tipo: "carrossel", cards } : null;
}

export function readInterativo(message: {
  role?: string | null;
  message_type?: string | null;
  metadata?: unknown;
}): Interativo | null {
  // Só a mensagem NOSSA é tela; o toque do lead (message_type "button") é desenhado pelo
  // chip "Clicou" (lib/button-click.ts) e nunca vira tela.
  if (message.role !== "assistant" || message.message_type === "button") return null;
  const raw = obj(obj(message.metadata)?.interativo);
  if (!raw) return null;
  switch (raw.tipo) {
    case "botoes":
      return lerBotoes(raw);
    case "lista":
      return lerLista(raw);
    case "carrossel":
      return lerCarrossel(raw);
    default:
      return null;
  }
}

/**
 * O corpo do carrossel sem os textos dos cards.
 *
 * O backend grava `content` = corpo + "\n\n" + textos dos cards, para o preview da lista
 * de conversas continuar sendo texto (valeria_runner_v2.py `_carrossel`). Na bolha os
 * textos já aparecem dentro dos cards, então repeti-los seria eco. Só corta quando o
 * `content` termina EXATAMENTE nos textos dos cards; qualquer outra forma volta inteira.
 */
export function carrosselCorpo(content: string, cards: InterativoCard[]): string {
  const sufixo = cards.map((c) => c.texto).join("\n\n");
  if (!sufixo) return content;
  if (content === sufixo) return "";
  if (content.endsWith(`\n\n${sufixo}`)) return content.slice(0, -(sufixo.length + 2));
  return content;
}

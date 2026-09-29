/**
 * Texto do LEAD que estava guardado na linha mas nunca chegava à tela.
 *
 * Uma janela do buffer vira UMA linha em `messages`, com UM slot de `message_type`
 * (backend/app/buffer/manager.py:35-48 + processor.py::_resolve_media). Então a legenda da
 * foto e a frase digitada logo depois de reagir moram no MESMO `content` da linha de mídia
 * ou de reação. O renderizador, porém, é um ternário por `message_type`
 * (message-bubble.tsx) que desenha a mídia/reação e nunca imprime `content` — e a linha de
 * reação ainda é filtrada inteira da thread (message-list.tsx) quando vira badge no alvo.
 * Resultado medido em produção (29/09/2026): 199 de 389 imagens e 123 de 383 reações
 * inbound carregavam texto invisível ao vendedor.
 *
 * Este módulo separa o que o lead escreveu dos marcadores sintéticos que o backend injeta
 * para o LLM (`[imagem]`, `[reagiu com 👍]`, `[audio transcrito: ...]`), que são sinal
 * interno e não pertencem à bolha.
 */

export interface MessageTextSource {
  message_type?: string | null;
  content?: string | null;
  document_name?: string | null;
  /** true quando o emoji já aparece como badge na bolha alvo (messages-window.ts). */
  reaction_attached?: boolean;
}

/** _MEDIA_MARKERS + marcadores de áudio do backend (processor.py:211-229). */
const SYNTHETIC_LINES = new Set([
  "[imagem]",
  "[documento]",
  "[vídeo]",
  "[figurinha]",
  "[áudio]",
  "[audio: nao foi possivel transcrever]",
]);

/** `[reagiu com <emoji>]` — inclui emoji com modificador de tom de pele. */
const REACTION_MARKER = /\[reagiu com [^\]]*\]/g;

/**
 * `[audio transcrito: ...]`. A transcrição no chat é um gap declarado e fora do escopo
 * deste fix — some junto com os marcadores para que sobre só o que o lead DIGITOU.
 */
const AUDIO_TRANSCRIPT = /\[audio transcrito:[^\]]*\]/g;

/** Tipos cuja bolha é desenhada pela mídia — o `content` deles é legenda, não corpo. */
const CAPTION_TYPES = new Set(["image", "video", "sticker", "document", "audio"]);

function stripSyntheticMarkers(raw: string): string {
  return raw
    .replace(REACTION_MARKER, "")
    .replace(AUDIO_TRANSCRIPT, "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !SYNTHETIC_LINES.has(line))
    .join("\n");
}

/**
 * Legenda que o lead anexou à mídia (ou o que ele digitou na mesma janela do buffer).
 * Vazio quando só havia o marcador sintético.
 */
export function mediaCaption(message: MessageTextSource): string {
  const type = message.message_type;
  if (!type || !CAPTION_TYPES.has(type)) return "";

  const caption = stripSyntheticMarkers(message.content ?? "");
  if (!caption) return "";

  // A bolha de documento já imprime `document_name`; repetir viraria eco.
  if (type === "document") {
    const filename = (message.document_name ?? "").trim();
    if (filename && caption === filename) return "";
  }

  return caption;
}

/** O que o lead escreveu na mesma janela em que reagiu — sem os `[reagiu com ...]`. */
export function reactionExtraText(message: MessageTextSource): string {
  if (message.message_type !== "reaction") return "";
  return stripSyntheticMarkers(message.content ?? "");
}

/**
 * True quando a linha de reação carrega texto próprio. Nesse caso ela NÃO pode ser
 * filtrada da thread em troca de um badge no alvo — o badge não mostra o que foi escrito.
 */
export function reactionRowHasOwnText(message: MessageTextSource): boolean {
  return reactionExtraText(message) !== "";
}

/**
 * A reação só pode sair da thread quando virou badge no alvo E não traz nada escrito.
 * Trocar a linha pelo badge era o que apagava a frase que o lead digitou logo depois
 * de reagir — o badge mostra o emoji, nunca o texto.
 */
export function shouldHideReactionRow(message: MessageTextSource): boolean {
  if (message.message_type !== "reaction") return false;
  return Boolean(message.reaction_attached) && !reactionRowHasOwnText(message);
}

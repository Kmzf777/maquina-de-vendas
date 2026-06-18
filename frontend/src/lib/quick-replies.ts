// frontend/src/lib/quick-replies.ts
import type { QuickReply } from "@/lib/types";

export interface SlashQuery {
  query: string; // texto após a "/" (filtro)
  start: number; // índice da "/" no texto completo
}

// Detecta um gatilho "/" ativo no texto até o caret. null se não houver.
export function getSlashQuery(text: string, caret: number): SlashQuery | null {
  const before = text.slice(0, caret);
  const match = before.match(/(?:^|\s)\/(\S*)$/);
  if (!match) return null;
  const query = match[1];
  return { query, start: caret - query.length - 1 };
}

// Substitui o trecho [start, caret) pelo conteúdo; retorna novo texto + posição do caret.
export function applyQuickReply(
  text: string,
  caret: number,
  start: number,
  content: string
): { text: string; caret: number } {
  const head = text.slice(0, start);
  const tail = text.slice(caret);
  return { text: head + content + tail, caret: head.length + content.length };
}

// Filtra por shortcut + título + conteúdo (case-insensitive). Query vazia → tudo.
export function filterQuickReplies(items: QuickReply[], query: string): QuickReply[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter(
    (it) =>
      (it.shortcut ?? "").toLowerCase().includes(q) ||
      it.title.toLowerCase().includes(q) ||
      it.content.toLowerCase().includes(q)
  );
}

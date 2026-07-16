import type { Message, MessageReaction, QuotedMessage, ReactionTarget } from "@/lib/types";

// Janela de mensagens do chat: a thread carrega as N mais recentes e pagina
// para trás sob demanda ("Carregar anteriores"). Antes a query buscava a
// conversa INTEIRA (sem limit) — threads longas custavam egress e render.
export const MESSAGE_PAGE_SIZE = 100;

/** Página cheia ⇒ provavelmente há mais histórico atrás dela. */
export function pageHasMore(fetchedCount: number): boolean {
  return fetchedCount >= MESSAGE_PAGE_SIZE;
}

/**
 * Deduplica por id e ordena por created_at ascendente. INSERTs de tempo real chegam
 * fora de ordem (e podem colidir com o refetch), então normalizamos aqui para evitar
 * mensagens no lugar errado / duplicadas na thread.
 */
export function normalizeOrder(raw: Message[]): Message[] {
  const byId = new Map<string, Message>();
  for (const m of raw) byId.set(m.id, m);
  return [...byId.values()].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );
}

function reactionTargetWamid(msg: Message): string | null {
  if (msg.message_type !== "reaction") return null;
  const meta = msg.metadata as { target_wamid?: unknown } | null | undefined;
  const target = meta?.target_wamid;
  return typeof target === "string" && target ? target : null;
}

function reactionEmoji(msg: Message): string {
  const meta = msg.metadata as { emoji?: unknown } | null | undefined;
  return typeof meta?.emoji === "string" && meta.emoji ? meta.emoji : "?";
}

/**
 * Enriquece a janela com citações (reply) e reações resolvidas.
 *
 * `lookup` são linhas trazidas do banco APENAS para resolução (fallback quando a
 * mensagem citada/reagida é mais antiga que a janela carregada) — nunca entram
 * na thread renderizada. Reações cujo alvo está NA janela viram badge na bolha
 * alvo (`reactions` no alvo + `reaction_attached` na reação); alvo só no lookup
 * mantém a bolha própria da reação, com `reaction_target` populado.
 */
export function enrichWithQuotedMessages(raw: Message[], lookup: Message[] = []): Message[] {
  const wamidMap = new Map<string, Message>();
  const idMap = new Map<string, Message>();
  const inWindow = new Set<string>();
  for (const msg of raw) {
    if (msg.wamid) {
      wamidMap.set(msg.wamid, msg);
      inWindow.add(msg.wamid);
    }
    idMap.set(msg.id, msg);
  }
  for (const row of lookup) {
    if (row.wamid && !wamidMap.has(row.wamid)) wamidMap.set(row.wamid, row);
  }

  // Badges: reações cujo alvo está na janela, agrupadas pelo wamid do alvo.
  const reactionsByTarget = new Map<string, MessageReaction[]>();
  for (const msg of raw) {
    const target = reactionTargetWamid(msg);
    if (!target || !inWindow.has(target)) continue;
    const list = reactionsByTarget.get(target) ?? [];
    list.push({ emoji: reactionEmoji(msg), role: msg.role });
    reactionsByTarget.set(target, list);
  }

  return raw.map((msg) => {
    let out = msg;

    const hasQuote = msg.quoted_wamid || msg.quoted_message_id;
    if (hasQuote) {
      const original =
        (msg.quoted_wamid ? wamidMap.get(msg.quoted_wamid) : undefined) ??
        (msg.quoted_message_id ? idMap.get(msg.quoted_message_id) : undefined);
      const quoted: QuotedMessage | null = original
        ? { id: original.id, content: original.content, role: original.role, message_type: original.message_type ?? null }
        : null;
      out = { ...out, quoted_message: quoted };
    }

    const targetWamid = reactionTargetWamid(msg);
    if (msg.message_type === "reaction") {
      const original = targetWamid ? wamidMap.get(targetWamid) : undefined;
      const target: ReactionTarget | null = original
        ? { id: original.id, content: original.content, role: original.role, message_type: original.message_type ?? null }
        : null;
      out = {
        ...out,
        reaction_target: target,
        reaction_attached: Boolean(targetWamid && inWindow.has(targetWamid)),
      };
    }

    const badges = msg.wamid ? reactionsByTarget.get(msg.wamid) : undefined;
    if (badges) {
      out = { ...out, reactions: badges };
    } else if (out.reactions) {
      // Idempotência: reação removida da janela não deixa badge fantasma.
      out = { ...out, reactions: undefined };
    }

    return out;
  });
}

/**
 * Wamids referenciados (citação ou alvo de reação) que a janela + enriquecimento
 * atual NÃO conseguiram resolver — candidatos ao fetch dirigido no banco.
 */
export function collectUnresolvedWamids(enriched: Message[]): string[] {
  const unresolved = new Set<string>();
  for (const msg of enriched) {
    if (msg.quoted_wamid && msg.quoted_message === null) {
      unresolved.add(msg.quoted_wamid);
    }
    const target = reactionTargetWamid(msg);
    if (target && msg.reaction_target === null) {
      unresolved.add(target);
    }
  }
  return [...unresolved];
}

/** Prepend de uma página mais antiga (asc) na janela atual, com dedup/ordenação. */
export function mergeOlderPage(current: Message[], olderAsc: Message[], lookup: Message[] = []): Message[] {
  return enrichWithQuotedMessages(normalizeOrder([...olderAsc, ...current]), lookup);
}

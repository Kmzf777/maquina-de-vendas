"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  conversationsListUrl,
  type ConversationsPage,
} from "@/app/api/conversations/list-params";
import type { Conversation, Lead } from "@/lib/types";

export interface DeepLinkLeadOptions {
  /** `lead_id` da URL (null quando não há ou depois de limpar a URL). */
  leadId: string | null;
  /** A lista inicial já carregou (antes disso não dá para procurar nela). */
  ready: boolean;
  conversations: Conversation[];
  ensureInList: (conv: Conversation) => void;
  /** Conversa achada: a página seleciona e, no celular, abre o chat. */
  onFound: (conv: Conversation) => void;
  /** Lead sem conversa visível: a página desfaz a seleção anterior. */
  onNotFound: () => void;
  /** Tira o `lead_id` da URL (router.replace). */
  clearUrl: () => void;
}

/**
 * Deep-link `/conversas?lead_id=` (cartão 70d844a6).
 *
 * Guarda o último lead APLICADO em vez de um booleano "já aplicou": um segundo link
 * (popup de SLA, notificação) com a página montada também precisa abrir. A URL
 * limpa (leadId null) zera a marca, então o mesmo lead pode vir de novo depois.
 *
 * Lead sem conversa visível (nenhuma, só bloqueada ou de canal sem acesso) vira
 * `leadSemConversa` para a página avisar, em vez de deixar a lista calada. Falha
 * de rede NÃO vira aviso: não dá para afirmar que a conversa não existe.
 */
export function useDeepLinkLead({
  leadId,
  ready,
  conversations,
  ensureInList,
  onFound,
  onNotFound,
  clearUrl,
}: DeepLinkLeadOptions): { leadSemConversa: string | null; dispensar: () => void } {
  const aplicado = useRef<string | null>(null);
  const [leadSemConversa, setLeadSemConversa] = useState<string | null>(null);

  // Callbacks por ref: a página recria as funções a cada render, e o efeito não
  // pode rodar de novo por isso.
  const cb = useRef({ ensureInList, onFound, onNotFound, clearUrl });
  useLayoutEffect(() => {
    cb.current = { ensureInList, onFound, onNotFound, clearUrl };
  });

  useEffect(() => {
    if (!leadId) {
      aplicado.current = null;
      return;
    }
    if (!ready || aplicado.current === leadId) return;
    aplicado.current = leadId;

    const match = conversations.find((c) => (c.leads as Lead | undefined | null)?.id === leadId);
    if (match) {
      cb.current.onFound(match);
      cb.current.clearUrl();
      return;
    }

    // Lead fora da lista carregada (paginação): busca sob demanda.
    void (async () => {
      try {
        const res = await fetch(conversationsListUrl({ leadId }));
        if (!res.ok) return;
        const data = (await res.json()) as ConversationsPage<Conversation>;
        if (aplicado.current !== leadId) return; // chegou outro link no meio
        const conv = Array.isArray(data?.conversations) ? data.conversations[0] : null; // a rota ordena por last_msg_at desc
        if (!conv) {
          setLeadSemConversa(leadId);
          cb.current.onNotFound();
          return;
        }
        cb.current.ensureInList(conv);
        cb.current.onFound(conv);
      } catch {
        // falha de rede: lista continua utilizável, sem aviso de "sem conversa"
      } finally {
        cb.current.clearUrl();
      }
    })();
  }, [leadId, ready, conversations]);

  const dispensar = useCallback(() => setLeadSemConversa(null), []);
  return { leadSemConversa, dispensar };
}

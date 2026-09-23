"use client";

import { useSyncExternalStore } from "react";

/**
 * Conversa que o vendedor está com aberta em /conversas. O popup de SLA lê este
 * valor para não interromper justamente a resposta ao lead que está atrasado.
 */
export interface ActiveConversation {
  conversationId: string | null;
  leadId: string | null;
}

const EMPTY: ActiveConversation = { conversationId: null, leadId: null };
let current: ActiveConversation = EMPTY;
const listeners = new Set<() => void>();

export function getActiveConversation(): ActiveConversation {
  return current;
}

export function setActiveConversation(next: ActiveConversation): void {
  if (next.conversationId === current.conversationId && next.leadId === current.leadId) return;
  current = next.conversationId === null && next.leadId === null ? EMPTY : { ...next };
  listeners.forEach((l) => l());
}

export function subscribeActiveConversation(cb: () => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

export function useActiveConversation(): ActiveConversation {
  return useSyncExternalStore(subscribeActiveConversation, getActiveConversation, () => EMPTY);
}

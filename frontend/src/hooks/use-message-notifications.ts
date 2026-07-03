"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import { shouldNotifyForMessage, isChannelAllowed, truncate } from "@/lib/notifications";
import type { Message } from "@/lib/types";

export interface MessageNotification {
  id: string;
  leadId: string;
  leadName: string;
  messagePreview: string;
  conversationId: string;
}

function playNotificationSound() {
  try {
    new Audio("/notification_audio.mp3").play().catch(() => {});
  } catch {
    // autoplay bloqueado ou arquivo ausente — ignorado silenciosamente
  }
}

interface ResolvedConversation {
  id: string;
  channel_id: string | null;
  lead: { id: string; name: string };
}

export function useMessageNotifications() {
  const [notifications, setNotifications] = useState<MessageNotification[]>([]);
  const supabase = useMemo(() => createClient(), []);

  // Escopo de canais do usuário logado (semântica de getAllowedChannelIds):
  // - undefined => ainda não carregado ou falhou → fail-closed (não notifica).
  // - null      => admin, sem restrição.
  // - string[]  => vendedor, restrito a esses canais.
  // Ref (não state) para o handler do Realtime ler o valor atual sem
  // reassinar o canal a cada mudança.
  const allowedChannelsRef = useRef<string[] | null | undefined>(undefined);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  // Carrega o escopo de canais no mount, com retry para falha transitória
  // (sem escopo carregado, NENHUMA notificação dispara — fail-closed).
  useEffect(() => {
    let cancelled = false;
    const RETRY_DELAYS_MS = [2000, 5000, 15000];

    async function loadScope(attempt = 0) {
      try {
        const res = await fetch("/api/me/allowed-channels");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { channel_ids: string[] | null };
        if (!cancelled) allowedChannelsRef.current = body.channel_ids;
      } catch (err) {
        if (cancelled) return;
        console.warn("[notif] falha ao carregar escopo de canais:", err);
        if (attempt < RETRY_DELAYS_MS.length) {
          setTimeout(() => loadScope(attempt + 1), RETRY_DELAYS_MS[attempt]);
        }
      }
    }

    loadScope();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Resolve a conversa (e o canal) da mensagem. Preferência pelo
    // conversation_id do próprio INSERT — determinístico em leads
    // multi-canal. Fallback por lead_id só para registros legados sem
    // conversation_id (raros), pegando a conversa mais recente.
    async function resolveConversation(msg: Message): Promise<ResolvedConversation | null> {
      let query = supabase
        .from("conversations")
        .select("id, channel_id, leads!inner(id, name)")
        .limit(1);

      query = msg.conversation_id
        ? query.eq("id", msg.conversation_id)
        : query.eq("lead_id", msg.lead_id).order("last_msg_at", { ascending: false, nullsFirst: false });

      const { data: rows } = await query;
      const conv = rows?.[0] ?? null;
      if (!conv) return null;

      const lead = (conv.leads as unknown) as { id: string; name: string } | null;
      if (!lead) return null;

      return { id: conv.id, channel_id: conv.channel_id ?? null, lead };
    }

    const channel = supabase
      .channel("global-message-notifications")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        async (payload) => {
          const msg = payload.new as Message;
          // Notifica TODA mensagem do contato (role=user), com IA ligada ou não.
          // Mensagens da IA (assistant) e de sistema não geram alerta.
          if (!shouldNotifyForMessage(msg)) return;

          const conv = await resolveConversation(msg);
          if (!conv) return;

          // Escopo por usuário: só notifica se o canal da conversa pertence
          // ao usuário logado (admin vê tudo). Sem isso, todo browser logado
          // tocava som/toast de mensagens de outros vendedores.
          if (!isChannelAllowed(conv.channel_id, allowedChannelsRef.current)) return;

          const notification: MessageNotification = {
            id: crypto.randomUUID(),
            leadId: conv.lead.id,
            leadName: conv.lead.name,
            messagePreview: truncate(msg.content || "(mídia)", 80),
            conversationId: conv.id,
          };

          playNotificationSound();
          setNotifications((prev) => [...prev.slice(-2), notification]);
        }
      )
      .subscribe((status) => {
        // Quieto no caminho feliz; loga só quando o canal degrada (diagnóstico futuro).
        if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
          console.warn("[notif] canal Realtime degradado:", status);
        }
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return { notifications, dismiss };
}

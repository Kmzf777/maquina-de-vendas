"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import { shouldNotifyForMessage, truncate } from "@/lib/notifications";
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

export function useMessageNotifications() {
  const [notifications, setNotifications] = useState<MessageNotification[]>([]);
  const supabase = useMemo(() => createClient(), []);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  useEffect(() => {
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

          // Busca nome do lead + id da conversa para montar o toast clicável.
          const { data: rows } = await supabase
            .from("conversations")
            .select("id, lead_id, leads!inner(id, name)")
            .eq("lead_id", msg.lead_id)
            .limit(1);

          const conv = rows?.[0] ?? null;
          if (!conv) return;

          const lead = (conv.leads as unknown) as { id: string; name: string } | null;
          if (!lead) return;

          const notification: MessageNotification = {
            id: crypto.randomUUID(),
            leadId: lead.id,
            leadName: lead.name,
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

"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
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
    // autoplay blocked or file missing — silently ignored
  }
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
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
          console.log("[Notif] evento recebido:", payload.new);
          const msg = payload.new as Message;

          if (msg.role !== "user") {
            console.log("[Notif] ignorado: role =", msg.role);
            return;
          }

          console.log("[Notif] mensagem de user, lead_id:", msg.lead_id);

          const { data: rows, error: convError } = await supabase
            .from("conversations")
            .select("id, lead_id, leads!inner(id, name, ai_enabled)")
            .eq("lead_id", msg.lead_id)
            .limit(1);

          console.log("[Notif] conversations query:", { rows, convError });

          const conv = rows?.[0] ?? null;
          if (!conv) {
            console.log("[Notif] nenhuma conversa encontrada");
            return;
          }

          const lead = (conv.leads as unknown) as { id: string; name: string; ai_enabled: boolean } | null;
          console.log("[Notif] lead:", lead);

          if (!lead) {
            console.log("[Notif] lead nulo");
            return;
          }

          if (lead.ai_enabled !== false) {
            console.log("[Notif] ignorado: ai_enabled =", lead.ai_enabled, "(só notifica quando AI está OFF)");
            return;
          }

          const notification: MessageNotification = {
            id: crypto.randomUUID(),
            leadId: lead.id,
            leadName: lead.name,
            messagePreview: truncate(msg.content || "(mídia)", 80),
            conversationId: conv.id,
          };

          console.log("[Notif] DISPARANDO notificação para:", lead.name);
          playNotificationSound();
          setNotifications((prev) => [...prev.slice(-2), notification]);
        }
      )
      .subscribe((status) => {
        console.log("[Notif] status do canal Realtime:", status);
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return { notifications, dismiss };
}

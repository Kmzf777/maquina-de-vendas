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
          const msg = payload.new as Message;
          if (msg.role !== "user") return;

          const { data: conv } = await supabase
            .from("conversations")
            .select("id, lead_id, leads!inner(id, name, ai_enabled)")
            .eq("lead_id", msg.lead_id)
            .maybeSingle();

          if (!conv) return;
          const leads = conv.leads as { id: string; name: string; ai_enabled: boolean }[] | null;
          if (!leads || !leads[0] || leads[0].ai_enabled !== false) return;
          const lead = leads[0];

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
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return { notifications, dismiss };
}

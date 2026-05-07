"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  useMessageNotifications,
  type MessageNotification,
} from "@/hooks/use-message-notifications";

interface ToastItemProps {
  notification: MessageNotification;
  onDismiss: () => void;
}

function ToastItem({ notification, onDismiss }: ToastItemProps) {
  const router = useRouter();

  // Ref pattern: timer set once on mount, always calls latest onDismiss
  const onDismissRef = useRef(onDismiss);
  useEffect(() => {
    onDismissRef.current = onDismiss;
  });

  useEffect(() => {
    const timer = setTimeout(() => onDismissRef.current(), 5000);
    return () => clearTimeout(timer);
  }, []); // empty deps — timer set once on mount

  function handleCardClick() {
    router.push(`/conversas?lead_id=${notification.leadId}`);
    onDismiss();
  }

  function handleDismissClick(e: React.MouseEvent) {
    e.stopPropagation();
    onDismiss();
  }

  return (
    <div
      role="alert"
      onClick={handleCardClick}
      className="pointer-events-auto flex items-start gap-3 w-[320px] bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3 cursor-pointer hover:bg-white transition-colors"
    >
      <div className="flex-1 min-w-0">
        <p className="text-[14px] font-semibold text-[#111111] leading-snug truncate">
          {notification.leadName}
        </p>
        <p className="text-[13px] text-[#7b7b78] leading-snug mt-0.5 line-clamp-2 break-words">
          {notification.messagePreview}
        </p>
      </div>

      <button
        onClick={handleDismissClick}
        aria-label="Fechar notificação"
        className="flex-shrink-0 mt-0.5 text-[#7b7b78] hover:text-[#111111] transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
  );
}

export function NotificationToast() {
  const { notifications, dismiss } = useMessageNotifications();

  if (notifications.length === 0) return null;

  return (
    <div
      aria-live="polite"
      className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none"
    >
      {notifications.map((n) => (
        <ToastItem key={n.id} notification={n} onDismiss={() => dismiss(n.id)} />
      ))}
    </div>
  );
}

import { useState } from "react";
import type { Message } from "@/lib/types";
import { formatTimeOnly } from "@/lib/datetime";

interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
  conversationId: string;
}

function getSenderBadge(message: Message): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  return null;
}

export function MessageBubble({ message, isGrouped, conversationId }: MessageBubbleProps) {
  const isFromMe = message.role === "assistant";
  const isTemp = message.id.startsWith("temp_");
  const [imgError, setImgError] = useState(false);
  const senderBadge = getSenderBadge(message);

  const isAudio = message.message_type === "audio";
  const isImage = message.message_type === "image";

  // New messages: media_url is a Supabase Storage URL (https://...) or object URL (blob:...)
  // Legacy messages: media_url is a Meta media_id (numeric string) — use proxy fallback
  const mediaSrc = message.media_url
    ? message.media_url.startsWith("http") || message.media_url.startsWith("blob:")
      ? message.media_url
      : `/api/media?media_id=${encodeURIComponent(message.media_url)}&conversation_id=${encodeURIComponent(conversationId)}`
    : null;

  return (
    <div
      className={`flex ${isFromMe ? "justify-end" : "justify-start"} ${isGrouped ? "mt-0.5" : "mt-2"}`}
    >
      <div
        className={`px-3 py-2 text-[14px] max-w-[75%] rounded-[8px] ${
          isFromMe
            ? "bg-[#111111] text-white ml-auto"
            : "bg-white border border-[#dedbd6] text-[#111111]"
        } ${isTemp ? "opacity-70" : ""}`}
      >
        {isAudio ? (
          mediaSrc ? (
            <audio
              controls
              src={mediaSrc}
              className="h-10 max-w-[240px]"
            />
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zm-1 3a1 1 0 0 1 2 0v8a1 1 0 0 1-2 0V4zm7.25 5a.75.75 0 0 0-1.5 0 5.75 5.75 0 0 1-11.5 0 .75.75 0 0 0-1.5 0 7.25 7.25 0 0 0 6.5 7.2V20H9a.75.75 0 0 0 0 1.5h6a.75.75 0 0 0 0-1.5h-2.25v-3.8A7.25 7.25 0 0 0 19.25 9z" />
              </svg>
              <span className="text-[13px] opacity-60">Áudio</span>
            </div>
          )
        ) : isImage ? (
          mediaSrc ? (
            imgError ? (
              <div className="flex items-center gap-2 py-1">
                <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 0 1 2.828 0L16 16m-2-2l1.586-1.586a2 2 0 0 1 2.828 0L20 14m-6-6h.01M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
                </svg>
                <span className="text-[13px] opacity-60">Imagem</span>
              </div>
            ) : (
              <img
                src={mediaSrc}
                alt="Imagem enviada"
                className="max-w-[240px] max-h-[320px] object-contain rounded-[4px] block"
                onError={() => setImgError(true)}
              />
            )
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 0 1 2.828 0L16 16m-2-2l1.586-1.586a2 2 0 0 1 2.828 0L20 14m-6-6h.01M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
              </svg>
              <span className="text-[13px] opacity-60">Imagem</span>
            </div>
          )
        ) : (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        )}
        <div className={`flex items-center gap-1 mt-1 ${isFromMe ? "justify-end" : "justify-start"}`}>
          <p
            className={`text-[11px] ${
              isFromMe ? "text-white/50" : "text-[#7b7b78]"
            }`}
          >
            {isTemp ? "Enviando..." : formatTimeOnly(message.created_at)}
          </p>
          {senderBadge && (
            <span
              className={`text-[10px] opacity-60 ${
                isFromMe ? "text-white" : "text-[#7b7b78]"
              }`}
            >
              · {senderBadge}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

import type { Message } from "@/lib/types";
import { formatTimeOnly } from "@/lib/datetime";

interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
}

function getSenderBadge(message: Message): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  return null;
}

export function MessageBubble({ message, isGrouped }: MessageBubbleProps) {
  const isFromMe = message.role === "assistant";
  const isTemp = message.id.startsWith("temp_");
  const senderBadge = getSenderBadge(message);

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
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
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

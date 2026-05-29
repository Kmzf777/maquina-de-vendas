import { useState } from "react";
import type { Message, QuotedMessage } from "@/lib/types";
import { formatTimeOnly } from "@/lib/datetime";

function DeliveryTick({ status }: { status?: "sent" | "delivered" | "read" | null }) {
  const isDouble = status === "delivered" || status === "read";
  const isRead = status === "read";
  const color = isRead ? "text-[#53bdeb]" : "text-white/50";

  if (!isDouble) {
    return (
      <svg className={`inline-block flex-shrink-0 ${color}`} width="12" height="9" viewBox="0 0 12 9" fill="none">
        <path d="M1 4.5L4.5 8L11 1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    );
  }
  return (
    <svg className={`inline-block flex-shrink-0 ${color}`} width="16" height="9" viewBox="0 0 16 9" fill="none">
      <path d="M1 4.5L4.5 8L11 1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M5 4.5L8.5 8L15 1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
  conversationId: string;
  onReply?: (msg: Message) => void;
  onScrollToMessage?: (messageId: string) => void;
  onContactDispatch?: (phone: string) => void;
}

function getSenderBadge(message: Message): string | null {
  if (message.role === "user") return null;
  if (message.sent_by === "agent") return "IA";
  if (message.sent_by === "seller") return "Vendedor";
  return null;
}

function getMediaLabel(messageType: string | null | undefined): string {
  switch (messageType) {
    case "image": return "📷 Imagem";
    case "audio": return "🎵 Áudio";
    case "video": return "🎬 Vídeo";
    case "document": return "📄 Documento";
    case "sticker": return "😀 Figurinha";
    case "location": return "📍 Localização";
    case "contact": return "👤 Contato";
    default: return "📎 Mídia";
  }
}

function QuotedBlock({
  quoted,
  isFromMe,
  onClick,
}: {
  quoted: QuotedMessage | null;
  isFromMe: boolean;
  onClick: () => void;
}) {
  const isText = !quoted?.message_type || quoted.message_type === "text";

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-md mb-1.5 overflow-hidden flex transition-colors ${
        isFromMe
          ? "bg-white/20 hover:bg-white/30"
          : "bg-black/5 hover:bg-black/10"
      }`}
    >
      <div className={`w-1 flex-shrink-0 rounded-l-md ${isFromMe ? "bg-white/50" : "bg-[#25d366]"}`} />
      <div className="px-2 py-1.5 min-w-0 flex-1">
        {!quoted ? (
          <p className={`text-xs italic ${isFromMe ? "text-white/50" : "text-[#7b7b78]"}`}>
            Mensagem original não disponível
          </p>
        ) : (
          <>
            <p className={`text-xs font-semibold mb-0.5 ${isFromMe ? "text-white/80" : "text-[#25d366]"}`}>
              {quoted.role === "user" ? "Lead" : "Você"}
            </p>
            <p className={`text-xs truncate ${isFromMe ? "text-white/60" : "text-[#555]"}`}>
              {isText
                ? (quoted.content ?? "")
                : getMediaLabel(quoted.message_type)}
            </p>
          </>
        )}
      </div>
    </button>
  );
}

export function MessageBubble({ message, isGrouped, conversationId, onReply, onScrollToMessage, onContactDispatch }: MessageBubbleProps) {
  const isFromMe = message.role === "assistant";
  const isTemp = message.id.startsWith("temp_");
  const [imgError, setImgError] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const senderBadge = getSenderBadge(message);

  const isAudio = message.message_type === "audio";
  const isImage = message.message_type === "image";
  const isDocument = message.message_type === "document";
  const isVideo = message.message_type === "video";
  const isSticker = message.message_type === "sticker";
  const isLocation = message.message_type === "location";
  const isContact = message.message_type === "contact";
  const isReaction = message.message_type === "reaction";

  // New messages: media_url is a Supabase Storage URL (https://...) or object URL (blob:...)
  // Legacy messages: media_url is a Meta media_id (numeric string) — use proxy fallback
  const mediaSrc = message.media_url
    ? message.media_url.startsWith("http") || message.media_url.startsWith("blob:")
      ? message.media_url
      : `/api/media?media_id=${encodeURIComponent(message.media_url)}&conversation_id=${encodeURIComponent(conversationId)}`
    : null;

  const replyBtn = onReply && !isTemp ? (
    <button
      onClick={() => onReply(message)}
      className="flex-shrink-0 self-center opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-full bg-[#e8e8e8] hover:bg-[#d8d8d8] text-[#666]"
      title="Responder"
      aria-label="Responder"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="9 17 4 12 9 7" />
        <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
      </svg>
    </button>
  ) : null;

  return (
    <div
      className={`flex group items-end gap-1 ${isFromMe ? "flex-row-reverse" : "flex-row"} ${isGrouped ? "mt-0.5" : "mt-2"}`}
    >
      {replyBtn}
      <div
        className={`px-3 py-2 text-[14px] max-w-[75%] rounded-[8px] ${
          isFromMe
            ? "bg-[#111111] text-white ml-auto"
            : "bg-white border border-[#dedbd6] text-[#111111]"
        } ${isTemp ? "opacity-70" : ""}`}
      >
        {(message.quoted_wamid || message.quoted_message !== undefined) && (
          <QuotedBlock
            quoted={message.quoted_message ?? null}
            isFromMe={isFromMe}
            onClick={() => {
              if (message.quoted_message?.id) {
                onScrollToMessage?.(message.quoted_message.id);
              }
            }}
          />
        )}
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
        ) : isVideo ? (
          mediaSrc ? (
            videoError ? (
              <div className="flex items-center gap-2 py-1">
                <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.069A1 1 0 0121 8.868v6.264a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <span className="text-[13px] opacity-60">Vídeo</span>
              </div>
            ) : (
              <video
                controls
                src={mediaSrc}
                className="max-w-[320px] max-h-[400px] rounded-[4px] block"
                onError={() => setVideoError(true)}
              />
            )
          ) : (
            <div className="flex items-center gap-2 py-1">
              <svg className="w-4 h-4 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.069A1 1 0 0121 8.868v6.264a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <span className="text-[13px] opacity-60">Vídeo</span>
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
        ) : isDocument ? (
          (() => {
            const docName = message.document_name || message.content || "Documento";
            const downloadHref = mediaSrc
              ? (() => {
                  if (mediaSrc.startsWith("http") || mediaSrc.startsWith("blob:")) {
                    return mediaSrc;
                  }
                  const url = new URL(mediaSrc, "http://x");
                  url.searchParams.set("download", "1");
                  url.searchParams.set("filename", docName);
                  return url.pathname + url.search;
                })()
              : null;
            return (
              <div className="flex items-center gap-2 py-1">
                <svg className="w-5 h-5 opacity-60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
                </svg>
                <div className="flex flex-col min-w-0">
                  <span className="text-[13px] truncate max-w-[180px]">{docName}</span>
                  {downloadHref && (
                    <a
                      href={downloadHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5"
                    >
                      Baixar
                    </a>
                  )}
                </div>
              </div>
            );
          })()
        ) : isSticker ? (
          mediaSrc ? (
            <img
              src={mediaSrc}
              alt="Sticker"
              className="max-w-[160px] max-h-[160px] object-contain block"
            />
          ) : (
            <span className="text-[13px] opacity-60">Sticker</span>
          )
        ) : isLocation ? (
          (() => {
            const meta = message.metadata as { lat?: number; lng?: number; name?: string; address?: string } | undefined;
            const mapsUrl = meta?.lat !== undefined && meta?.lng !== undefined
              ? `https://maps.google.com/?q=${meta.lat},${meta.lng}`
              : null;
            return (
              <div className="flex items-start gap-2 py-1">
                <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-red-500" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
                </svg>
                <div className="flex flex-col min-w-0">
                  {(meta?.name || meta?.address) && (
                    <span className="text-[13px]">{meta.name || meta.address}</span>
                  )}
                  {mapsUrl && (
                    <a
                      href={mapsUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] underline opacity-70 hover:opacity-100 mt-0.5"
                    >
                      Ver no mapa
                    </a>
                  )}
                  {!meta?.name && !meta?.address && !mapsUrl && (
                    <span className="text-[13px] opacity-60">Localização</span>
                  )}
                </div>
              </div>
            );
          })()
        ) : isContact ? (
          (() => {
            const meta = message.metadata as { name?: string; phone?: string; vcard?: string } | undefined;
            const vcardUrl = meta?.vcard
              ? `data:text/vcard;charset=utf-8,${encodeURIComponent(meta.vcard)}`
              : null;
            return (
              <div className="rounded-[8px] border border-[#dedbd6] bg-white overflow-hidden min-w-[200px] max-w-[240px] -mx-1 -my-1">
                {/* Header: avatar + name + phone */}
                <div className="px-3 py-2.5 flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-full bg-[#f0ede8] flex-shrink-0 flex items-center justify-center">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#7b7b78" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                      <circle cx="12" cy="7" r="4"/>
                    </svg>
                  </div>
                  <div className="flex flex-col min-w-0">
                    {meta?.name ? (
                      <span className="text-[13px] font-medium text-[#111111] leading-tight truncate">{meta.name}</span>
                    ) : (
                      <span className="text-[13px] font-medium text-[#111111] leading-tight">Contato</span>
                    )}
                    {meta?.phone && (
                      <span className="text-[12px] text-[#7b7b78] leading-tight truncate">{meta.phone}</span>
                    )}
                    {vcardUrl && (
                      <a
                        href={vcardUrl}
                        download={`${meta?.name || "contato"}.vcf`}
                        className="text-[11px] text-[#7b7b78] opacity-70 hover:opacity-100 underline mt-0.5 leading-tight"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Baixar contato
                      </a>
                    )}
                  </div>
                </div>
                {/* Action button */}
                {meta?.phone && onContactDispatch && (
                  <>
                    <div className="border-t border-[#dedbd6]" />
                    <button
                      onClick={() => onContactDispatch(meta.phone!)}
                      className="w-full px-3 py-2 text-[12px] text-[#111111] hover:bg-[#f0ede8] transition-colors flex items-center gap-1.5"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13"/>
                        <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                      </svg>
                      Chamar contato
                    </button>
                  </>
                )}
              </div>
            );
          })()
        ) : isReaction ? (
          (() => {
            const meta = message.metadata as { emoji?: string } | undefined;
            return (
              <span className="text-[12px] opacity-60 italic">
                Reagiu: {meta?.emoji ?? "?"}
              </span>
            );
          })()
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
          {isFromMe && !isTemp && (
            <DeliveryTick status={message.delivery_status} />
          )}
        </div>
      </div>
    </div>
  );
}

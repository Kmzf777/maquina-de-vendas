"use client";

import { useState, useEffect, useRef, useMemo, type ChangeEvent } from "react";
import type { Message, Conversation, Tag, QuickReply } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import { getWindowStatus } from "@/lib/window-status";
import { TemplateDispatchModal } from "@/components/conversas/template-dispatch-modal";
import { ChatHeader } from "@/components/conversas/chat-header";
import { MessageList, type MessageListHandle } from "@/components/conversas/message-list";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
import { QuickSendModal } from "@/components/campaigns/quick-send-modal";
import { useRouter } from "next/navigation";
import { QuickReplyMenu } from "@/components/conversas/quick-reply-menu";
import { getSlashQuery, applyQuickReply, filterQuickReplies } from "@/lib/quick-replies";
import { resolveLeadVariables } from "@/lib/lead-variables";

export interface SiblingConversationSummary {
  id: string;
  channelName: string;
}

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onMarkRead?: () => void | Promise<void>;
  onBack?: () => void;
  onOpenContact?: () => void;
  siblingConversations?: SiblingConversationSummary[];
  onSelectSibling?: (conversationId: string) => void;
  targetMessageId?: string | null;
  onTargetConsumed?: () => void;
}

export function ChatView({ conversation, tags, aiEnabled, togglingAi, onToggleAi, followupEnabled, togglingFollowup, onToggleFollowup, onMarkRead, onBack, onOpenContact, siblingConversations, onSelectSibling, targetMessageId, onTargetConsumed }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const { messages, loading, refetch } = useRealtimeMessages(conversation.id ?? null);

  // Pulo para a mensagem buscada: espera as mensagens carregarem (DOM populado) e
  // chama o scrollToMessage já existente; dispara uma única vez por alvo.
  useEffect(() => {
    if (!targetMessageId || loading) return;
    const raf = requestAnimationFrame(() => {
      messageListRef.current?.scrollToMessage(targetMessageId);
      onTargetConsumed?.();
    });
    return () => cancelAnimationFrame(raf);
  }, [targetMessageId, loading, conversation.id, onTargetConsumed]);

  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const router = useRouter();
  const [quickReplies, setQuickReplies] = useState<QuickReply[]>([]);
  const [qrOpen, setQrOpen] = useState(false);
  const [qrQuery, setQrQuery] = useState("");
  const [qrIndex, setQrIndex] = useState(0);
  const [sending, setSending] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [dispatchSuccess, setDispatchSuccess] = useState(false);
  const [quickSendPhone, setQuickSendPhone] = useState<string | null>(null);
  const [replyingTo, setReplyingTo] = useState<Message | null>(null);
  const [optOutLoading, setOptOutLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const messageListRef = useRef<MessageListHandle>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoSendAfterStopRef = useRef(false);

  // Media states
  const [mediaState, setMediaState] = useState<'idle' | 'recording' | 'previewing' | 'sendingMedia'>('idle');
  const [mediaBlob, setMediaBlob] = useState<Blob | null>(null);
  const [mediaFilename, setMediaFilename] = useState<string>("");
  const [mediaObjectUrl, setMediaObjectUrl] = useState<string | null>(null);
  const [mediaMessageType, setMediaMessageType] = useState<'audio' | 'image' | 'document' | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const provider = channel?.provider ?? null;
  // Janela 24h POR CANAL: usa o campo da conversa (lead+canal), não o global do lead.
  const lastCustomerMsgAt = conversation.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const isInputBlocked = windowStatus === "closed";
  useEffect(() => {
    setOptimisticMessages([]);
    setShowTemplateModal(false);
    setDispatchSuccess(false);
    setQuickSendPhone(null);
    setReplyingTo(null);
    setMediaState('idle');
    setMediaBlob(null);
    setMediaFilename("");
    setMediaMessageType(null);
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    setMediaObjectUrl(null);
    chunksRef.current = [];
    setRecordingSeconds(0);
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    setQrOpen(false);
    setQrQuery("");
    setQrIndex(0);
  }, [conversation.id]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, [conversation.id]);

  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
      mediaRecorderRef.current?.stop();
    };
  }, []);

  useEffect(() => {
    fetch("/api/quick-replies")
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => setQuickReplies(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  const qrFiltered = useMemo(() => filterQuickReplies(quickReplies, qrQuery), [quickReplies, qrQuery]);

  const displayMessages = useMemo(
    () => [...messages, ...optimisticMessages],
    [messages, optimisticMessages]
  );

  function handleContactDispatch(phone: string) {
    setQuickSendPhone(phone);
  }

  async function handleOptOut() {
    if (optOutLoading) return;
    const confirmed = window.confirm(
      "Parar mensagens para este lead?\n\nIsso irá:\n• Desativar a IA (Valéria)\n• Mover os deals para a Blacklist\n• Cancelar follow-ups pendentes\n\nEsta ação não pode ser desfeita automaticamente."
    );
    if (!confirmed) return;

    const leadId = lead?.id;
    if (!leadId) return;

    setOptOutLoading(true);
    try {
      const res = await fetch(`/api/leads/${leadId}/optout`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.error || "Falha ao parar mensagens. Tente novamente.");
        return;
      }
      await onToggleAi();
    } catch {
      alert("Erro ao conectar ao servidor. Tente novamente.");
    } finally {
      setOptOutLoading(false);
    }
  }

  async function handleSend() {
    if (!text.trim() || sendingRef.current || isInputBlocked) return;
    sendingRef.current = true;
    const content = text.trim();

    const tempMsg: Message = {
      id: `temp_${Date.now()}`,
      lead_id: lead?.id ?? "",
      role: "assistant",
      content,
      stage: null,
      sent_by: "seller",
      created_at: new Date().toISOString(),
      ...(replyingTo?.wamid
        ? {
            quoted_wamid: replyingTo.wamid,
            quoted_message: {
              id: replyingTo.id,
              content: replyingTo.content,
              role: replyingTo.role,
              message_type: replyingTo.message_type ?? null,
            },
          }
        : {}),
    };

    setText("");
    setOptimisticMessages((prev) => [...prev, tempMsg]);
    setSending(true);

    try {
      const controller = new AbortController();
      abortRef.current = controller;
      const res = await fetch(`/api/conversations/${conversation.id}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: content,
          ...(replyingTo?.wamid ? { quoted_wamid: replyingTo.wamid } : {}),
          ...(replyingTo ? { quoted_message_id: replyingTo.id } : {}),
        }),
        signal: controller.signal,
        keepalive: true,
      });
      if (!res.ok) {
        setText(content);
      } else {
        refetch().catch(() => {});
      }
    } catch (err) {
      if (!(err instanceof Error && err.name === "AbortError")) {
        setText(content);
      }
    } finally {
      setOptimisticMessages((prev) => prev.filter((m) => m.id !== tempMsg.id));
      setSending(false);
      sendingRef.current = false;
      setReplyingTo(null);
    }
  }

  function handleTextChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setText(value);
    const caret = e.target.selectionStart ?? value.length;
    const slash = getSlashQuery(value, caret);
    if (slash) {
      setQrOpen(true);
      setQrQuery(slash.query);
      setQrIndex(0);
    } else {
      setQrOpen(false);
    }
  }

  function insertQuickReply(item: QuickReply) {
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? text.length;
    const slash = getSlashQuery(text, caret);
    const start = slash ? slash.start : caret;
    const resolved = resolveLeadVariables(item.content, lead ?? {});
    const result = applyQuickReply(text, caret, start, resolved);
    setText(result.text);
    setQrOpen(false);
    setQrQuery("");
    requestAnimationFrame(() => {
      const node = textareaRef.current;
      if (node) {
        node.focus();
        node.setSelectionRange(result.caret, result.caret);
      }
    });
  }

  function handleCreateQuickReply() {
    setQrOpen(false);
    router.push("/config?tab=respostas-rapidas&new=1");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (qrOpen) {
      if (e.key === "Escape") { e.preventDefault(); setQrOpen(false); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setQrIndex((i) => Math.min(i + 1, Math.max(qrFiltered.length - 1, 0))); return; }
      if (e.key === "ArrowUp")   { e.preventDefault(); setQrIndex((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (qrFiltered.length > 0) {
          insertQuickReply(qrFiltered[qrIndex] ?? qrFiltered[0]);
        } else {
          setQrOpen(false);
        }
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function cancelMedia() {
    autoSendAfterStopRef.current = false;
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    setMediaBlob(null);
    setMediaFilename("");
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    mediaRecorderRef.current?.stop();
  }

  function cancelRecording() {
    autoSendAfterStopRef.current = false;
    chunksRef.current = [];
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    setRecordingSeconds(0);
    setMediaState('idle');
    // Stop without firing onstop side-effects by overwriting handler temporarily
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.stop();
    }
  }

  function handleSendFromRecording() {
    autoSendAfterStopRef.current = true;
    stopRecording();
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/ogg')
        ? 'audio/ogg'
        : '';

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
        if (chunksRef.current.length === 0) return;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const objectUrl = URL.createObjectURL(blob);

        if (autoSendAfterStopRef.current) {
          autoSendAfterStopRef.current = false;
          // Send directly without preview
          const tempMsg: Message = {
            id: `temp_media_${Date.now()}`,
            lead_id: lead?.id ?? '',
            role: 'assistant',
            content: '',
            stage: null,
            sent_by: 'seller',
            created_at: new Date().toISOString(),
            message_type: 'audio',
            media_url: objectUrl,
          };
          setOptimisticMessages(prev => [...prev, tempMsg]);
          setMediaState('sendingMedia');

          const fd = new FormData();
          fd.append('file', blob, 'audio.webm');
          fd.append('filename', 'audio.webm');

          const controller = new AbortController();
          abortRef.current = controller;
          fetch(`/api/conversations/${conversation.id}/send-media`, {
            method: 'POST',
            body: fd,
            signal: controller.signal,
          })
            .then(async (res) => {
              if (!res.ok) {
                const data = await res.json().catch(() => ({ error: 'Falha ao enviar' }));
                alert(data.error || 'Falha ao enviar');
              } else {
                refetch().catch(() => {});
              }
            })
            .catch((err) => {
              if (!(err instanceof Error && err.name === 'AbortError')) {
                alert('Falha ao enviar áudio');
              }
            })
            .finally(() => {
              setOptimisticMessages(prev => prev.filter(m => m.id !== tempMsg.id));
              setMediaState('idle');
              setRecordingSeconds(0);
              URL.revokeObjectURL(objectUrl);
            });
        } else {
          setMediaBlob(blob);
          setMediaObjectUrl(objectUrl);
          setMediaMessageType('audio');
          setMediaState('previewing');
          setRecordingSeconds(0);
        }
      };

      recorder.start();
      setRecordingSeconds(0);
      setMediaState('recording');
      recordingTimerRef.current = setInterval(() => setRecordingSeconds(s => s + 1), 1000);
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        alert('Permissão de microfone negada. Habilite o microfone nas configurações do navegador.');
      } else if (name === 'NotFoundError') {
        alert('Nenhum microfone encontrado.');
      }
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  function handleFileSelect(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    const type: 'audio' | 'image' | 'document' =
      file.type.startsWith('audio/') ? 'audio'
      : file.type.startsWith('image/') ? 'image'
      : 'document';

    const MAX_SIZE = type === 'document' ? 100 * 1024 * 1024 : 16 * 1024 * 1024;
    const MAX_LABEL = type === 'document' ? '100MB' : '16MB';
    if (file.size > MAX_SIZE) {
      alert(`Arquivo muito grande. Máximo ${MAX_LABEL}.`);
      e.target.value = '';
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setMediaBlob(file);
    setMediaFilename(file.name);
    setMediaObjectUrl(objectUrl);
    setMediaMessageType(type);
    setMediaState('previewing');
    e.target.value = '';
  }

  async function handleSendMedia() {
    if (!mediaBlob || !mediaMessageType || !mediaObjectUrl) return;

    setMediaState('sendingMedia');

    const capturedFilename = mediaFilename;

    const tempMsg: Message = {
      id: `temp_media_${Date.now()}`,
      lead_id: lead?.id ?? '',
      role: 'assistant',
      content: mediaMessageType === 'document' ? capturedFilename : '',
      stage: null,
      sent_by: 'seller',
      created_at: new Date().toISOString(),
      message_type: mediaMessageType,
      media_url: mediaObjectUrl,
    };
    setOptimisticMessages(prev => [...prev, tempMsg]);

    const blobToSend = mediaBlob;
    const urlToRevoke = mediaObjectUrl;
    const typeToSend = mediaMessageType;

    setMediaBlob(null);
    setMediaFilename("");
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');

    try {
      const fd = new FormData();
      const filenameToSend = capturedFilename || (
        typeToSend === 'audio' ? 'audio.webm'
        : typeToSend === 'image' ? 'image.jpg'
        : 'documento'
      );
      fd.append('file', blobToSend, filenameToSend);
      fd.append('filename', filenameToSend);

      const controller = new AbortController();
      abortRef.current = controller;
      const res = await fetch(`/api/conversations/${conversation.id}/send-media`, {
        method: 'POST',
        body: fd,
        signal: controller.signal,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({ error: 'Falha ao enviar' }));
        alert(data.error || 'Falha ao enviar');
      } else {
        refetch().catch(() => {});
      }
    } catch (err) {
      if (!(err instanceof Error && err.name === 'AbortError')) {
        alert('Falha ao enviar mídia');
      }
    } finally {
      setOptimisticMessages(prev => prev.filter(m => m.id !== tempMsg.id));
      URL.revokeObjectURL(urlToRevoke);
    }
  }

  return (
    <div className="flex-1 min-w-0 flex flex-col h-full bg-[#faf9f6]">
      <ChatHeader
        conversation={conversation}
        tags={tags}
        aiEnabled={aiEnabled}
        togglingAi={togglingAi}
        onToggleAi={onToggleAi}
        followupEnabled={followupEnabled}
        togglingFollowup={togglingFollowup}
        onToggleFollowup={onToggleFollowup}
        onMarkRead={onMarkRead}
        onBack={onBack}
        onOpenContact={onOpenContact}
        onOptOut={handleOptOut}
      />

      {/* Sibling-conversation indicator: same lead, different channel */}
      {siblingConversations && siblingConversations.length > 0 && (
        <div className="flex items-center gap-2 border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-2 text-sm text-[#626260]" role="status">
          <svg className="w-3.5 h-3.5 flex-shrink-0 text-[#1e6ee8]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span className="text-[#7b7b78]">Este lead tem outra conversa</span>
          {siblingConversations.length === 1 ? (
            <>
              <span className="font-medium text-[#111111]">{siblingConversations[0].channelName}</span>
              {onSelectSibling && (
                <button
                  type="button"
                  onClick={() => onSelectSibling(siblingConversations[0].id)}
                  className="ml-auto text-xs text-[#1e6ee8] hover:underline flex-shrink-0 font-medium"
                >
                  Ver conversa
                </button>
              )}
            </>
          ) : (
            <>
              <span className="font-medium text-[#111111]">{siblingConversations.length} canais</span>
              <div className="ml-auto flex items-center gap-2 flex-shrink-0">
                {siblingConversations.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => onSelectSibling?.(s.id)}
                    className="text-xs text-[#1e6ee8] hover:underline font-medium"
                  >
                    {s.channelName}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <MessageList
        ref={messageListRef}
        key={conversation.id}
        messages={displayMessages}
        loading={loading}
        conversationId={conversation.id}
        onContactDispatch={handleContactDispatch}
        onReply={(msg) => setReplyingTo(msg)}
      />

      <WhatsappWindowIndicator
        expiresAt={conversation.whatsapp_window_expires_at}
        variant="banner"
        onReactivate={() => setShowTemplateModal(true)}
      />

      {/* Input or locked dispatch card */}
      {isInputBlocked ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-4 flex-shrink-0">
          {dispatchSuccess ? (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3 flex items-center gap-3">
              <span className="inline-block h-2 w-2 rounded-full bg-[#5aad65] flex-shrink-0" />
              <p className="text-[13px] text-[#111111]">
                Template enviado. Aguardando resposta do lead para reabrir a janela.
              </p>
            </div>
          ) : (
            <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-[13px] font-medium text-[#111111]">Janela de 24h encerrada</p>
                <p className="text-[12px] text-[#7b7b78] mt-0.5">
                  Envie um template aprovado para reabrir a conversa.
                </p>
              </div>
              <button
                onClick={() => setShowTemplateModal(true)}
                className="bg-[#111111] text-white text-[13px] px-4 py-2 rounded-[4px] transition-transform hover:scale-110 active:scale-[0.85] flex-shrink-0"
              >
                Iniciar disparo
              </button>
            </div>
          )}
        </div>
      ) : mediaState === 'previewing' || mediaState === 'sendingMedia' ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex flex-col gap-2 flex-shrink-0">
          {mediaMessageType === 'audio' && mediaObjectUrl && (
            <audio controls src={mediaObjectUrl} className="w-[240px] h-10" />
          )}
          {mediaMessageType === 'image' && mediaObjectUrl && (
            <img src={mediaObjectUrl} alt="preview" className="max-h-40 rounded-[4px] object-contain self-start" />
          )}
          {mediaMessageType === 'document' && mediaObjectUrl && (
            <div className="flex items-center gap-2 py-1 px-2 bg-white border border-[#dedbd6] rounded-[6px] self-start max-w-full">
              <svg className="w-5 h-5 flex-shrink-0 text-[#7b7b78]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z" />
              </svg>
              <span className="text-[13px] text-[#111111] truncate max-w-[220px]">
                {mediaFilename || "Documento"}
              </span>
            </div>
          )}
          <div className="flex gap-2 justify-end">
            <button
              onClick={cancelMedia}
              disabled={mediaState === 'sendingMedia'}
              className="cursor-pointer px-4 py-2 text-[13px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#f5f5f5] transition-all hover:scale-105 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Cancelar
            </button>
            <button
              onClick={handleSendMedia}
              disabled={mediaState === 'sendingMedia'}
              className="cursor-pointer bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[13px] hover:scale-105 transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {mediaState === 'sendingMedia' ? 'Enviando...' : 'Enviar'}
            </button>
          </div>
        </div>
      ) : mediaState === 'recording' ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] px-3 py-2.5 flex items-center gap-3 flex-shrink-0">
          {/* Discard */}
          <button
            onClick={cancelRecording}
            title="Descartar gravação"
            className="cursor-pointer text-[#aaa] hover:text-red-500 transition-all hover:scale-110 flex-shrink-0 p-1.5 rounded-full hover:bg-red-50"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              <path d="M10 11v6M14 11v6" />
              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
            </svg>
          </button>

          {/* Timer */}
          <div className="flex-1 flex items-center justify-center gap-2.5">
            <span className="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
            <span className="text-[14px] font-mono text-[#111111] tabular-nums">
              {String(Math.floor(recordingSeconds / 60)).padStart(2, '0')}:{String(recordingSeconds % 60).padStart(2, '0')}
            </span>
          </div>

          {/* Send */}
          <button
            onClick={handleSendFromRecording}
            title="Enviar áudio"
            className="cursor-pointer text-white bg-[#25d366] hover:bg-[#1db954] transition-all hover:scale-110 flex-shrink-0 p-2 rounded-full shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      ) : (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] flex flex-col flex-shrink-0">
          {/* Reply preview */}
          {replyingTo && (
            <div className="mx-3 mt-2 mb-1 flex items-center gap-2 rounded-lg border-l-4 border-[#25d366] bg-[#f7f7f7] pl-2 pr-3 py-2">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-[#25d366] mb-0.5">
                  {replyingTo.role === "user" ? "Lead" : "Você"}
                </p>
                <p className="text-xs text-[#666] truncate">
                  {replyingTo.message_type && replyingTo.message_type !== "text"
                    ? ({
                        image: "📷 Imagem",
                        audio: "🎵 Áudio",
                        video: "🎬 Vídeo",
                        document: "📄 Documento",
                        sticker: "😀 Figurinha",
                      } as Record<string, string>)[replyingTo.message_type] ?? "📎 Mídia"
                    : replyingTo.content}
                </p>
              </div>
              <button
                onClick={() => setReplyingTo(null)}
                className="text-[#999] hover:text-[#333] transition-colors flex-shrink-0"
                aria-label="Cancelar resposta"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          )}
          <div className="relative p-3 flex gap-2">
          {qrOpen && (
            <QuickReplyMenu
              items={qrFiltered}
              highlightedIndex={qrIndex}
              onSelect={insertQuickReply}
              onCreate={handleCreateQuickReply}
              onHighlight={setQrIndex}
            />
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,image/*,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
            onChange={handleFileSelect}
            className="hidden"
          />
          <button
            onClick={startRecording}
            disabled={isInputBlocked}
            title="Gravar áudio"
            className="cursor-pointer text-[#7b7b78] hover:text-[#111111] hover:scale-105 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 self-end pb-[9px]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
              <line x1="8" y1="23" x2="16" y2="23" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} />
            </svg>
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isInputBlocked}
            title="Anexar arquivo"
            className="cursor-pointer text-[#7b7b78] hover:text-[#111111] hover:scale-105 transition-all disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 self-end pb-[9px]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 1 0 2.828 2.828l6.414-6.586a4 4 0 0 0-5.656-5.656l-6.415 6.585a6 6 0 1 0 8.486 8.486L20.5 13" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onBlur={() => setQrOpen(false)}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="cursor-pointer bg-[#111111] text-white px-3 py-2 rounded-[4px] text-[14px] transition-all hover:scale-105 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0 self-end"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
          </div>
        </div>
      )}

      {showTemplateModal && (
        <TemplateDispatchModal
          conversation={conversation}
          onClose={() => setShowTemplateModal(false)}
          onSuccess={() => {
            setShowTemplateModal(false);
            setDispatchSuccess(true);
          }}
        />
      )}

      <QuickSendModal
        open={quickSendPhone !== null}
        onClose={() => setQuickSendPhone(null)}
        onSuccess={() => setQuickSendPhone(null)}
        prefillPhone={quickSendPhone ?? undefined}
      />
    </div>
  );
}

"use client";

import { useState, useEffect, useRef, useMemo, type ChangeEvent } from "react";
import type { Message, Conversation, Tag } from "@/lib/types";
import { useRealtimeMessages } from "@/hooks/use-realtime-messages";
import { getWindowStatus } from "@/lib/window-status";
import { TemplateDispatchModal } from "@/components/conversas/template-dispatch-modal";
import { ChatHeader } from "@/components/conversas/chat-header";
import { MessageList } from "@/components/conversas/message-list";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
  onBack?: () => void;
  onOpenContact?: () => void;
}

export function ChatView({ conversation, tags, aiEnabled, togglingAi, onToggleAi, followupEnabled, togglingFollowup, onToggleFollowup, onBack, onOpenContact }: ChatViewProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const { messages, loading, refetch } = useRealtimeMessages(lead?.id ?? null);
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [dispatchSuccess, setDispatchSuccess] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // Media states
  const [mediaState, setMediaState] = useState<'idle' | 'recording' | 'previewing' | 'sendingMedia'>('idle');
  const [mediaBlob, setMediaBlob] = useState<Blob | null>(null);
  const [mediaObjectUrl, setMediaObjectUrl] = useState<string | null>(null);
  const [mediaMessageType, setMediaMessageType] = useState<'audio' | 'image' | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const provider = channel?.provider ?? null;
  const lastCustomerMsgAt = lead?.last_customer_message_at ?? null;
  const windowStatus = getWindowStatus(lastCustomerMsgAt, provider);
  const isInputBlocked = windowStatus === "closed";
  useEffect(() => {
    setOptimisticMessages([]);
    setShowTemplateModal(false);
    setDispatchSuccess(false);
    setMediaState('idle');
    setMediaBlob(null);
    setMediaMessageType(null);
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    setMediaObjectUrl(null);
    chunksRef.current = [];
    setRecordingSeconds(0);
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
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

  const displayMessages = useMemo(
    () => [...messages, ...optimisticMessages],
    [messages, optimisticMessages]
  );

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
        body: JSON.stringify({ text: content }),
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
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function cancelMedia() {
    if (mediaObjectUrl) URL.revokeObjectURL(mediaObjectUrl);
    setMediaBlob(null);
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');
    if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
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
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const objectUrl = URL.createObjectURL(blob);
        setMediaBlob(blob);
        setMediaObjectUrl(objectUrl);
        setMediaMessageType('audio');
        setMediaState('previewing');
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
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

    const MAX_SIZE = 16 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      alert('Arquivo muito grande. Máximo 16MB.');
      e.target.value = '';
      return;
    }

    const type = file.type.startsWith('audio/') ? 'audio'
      : file.type.startsWith('image/') ? 'image'
      : null;

    if (!type) {
      alert('Tipo não suportado. Use áudio ou imagem.');
      e.target.value = '';
      return;
    }

    const objectUrl = URL.createObjectURL(file);
    setMediaBlob(file);
    setMediaObjectUrl(objectUrl);
    setMediaMessageType(type);
    setMediaState('previewing');
    e.target.value = '';
  }

  async function handleSendMedia() {
    if (!mediaBlob || !mediaMessageType || !mediaObjectUrl) return;

    setMediaState('sendingMedia');

    const tempMsg: Message = {
      id: `temp_media_${Date.now()}`,
      lead_id: lead?.id ?? '',
      role: 'assistant',
      content: '',
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
    setMediaObjectUrl(null);
    setMediaMessageType(null);
    setMediaState('idle');

    try {
      const fd = new FormData();
      const ext = blobToSend instanceof File
        ? blobToSend.name.split('.').pop() || (typeToSend === 'audio' ? 'webm' : 'jpg')
        : (typeToSend === 'audio' ? 'webm' : 'jpg');
      const filename = `${typeToSend}.${ext}`;
      fd.append('file', blobToSend, filename);

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
    <div className="flex-1 flex flex-col h-full bg-[#faf9f6]">
      <ChatHeader
        conversation={conversation}
        tags={tags}
        aiEnabled={aiEnabled}
        togglingAi={togglingAi}
        onToggleAi={onToggleAi}
        followupEnabled={followupEnabled}
        togglingFollowup={togglingFollowup}
        onToggleFollowup={onToggleFollowup}
        onBack={onBack}
        onOpenContact={onOpenContact}
      />

      <MessageList
        key={conversation.id}
        messages={displayMessages}
        loading={loading}
        conversationId={conversation.id}
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
            <audio controls src={mediaObjectUrl} className="w-full h-10" />
          )}
          {mediaMessageType === 'image' && mediaObjectUrl && (
            <img src={mediaObjectUrl} alt="preview" className="max-h-40 rounded-[4px] object-contain self-start" />
          )}
          <div className="flex gap-2 justify-end">
            <button
              onClick={cancelMedia}
              disabled={mediaState === 'sendingMedia'}
              className="px-4 py-2 text-[13px] border border-[#dedbd6] rounded-[4px] text-[#111111] disabled:opacity-40"
            >
              Cancelar
            </button>
            <button
              onClick={handleSendMedia}
              disabled={mediaState === 'sendingMedia'}
              className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[13px] disabled:opacity-40"
            >
              {mediaState === 'sendingMedia' ? 'Enviando...' : 'Enviar'}
            </button>
          </div>
        </div>
      ) : mediaState === 'recording' ? (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex items-center gap-3 flex-shrink-0">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500 animate-pulse flex-shrink-0" />
          <span className="text-[13px] text-[#111111]">
            {String(Math.floor(recordingSeconds / 60)).padStart(2, '0')}:{String(recordingSeconds % 60).padStart(2, '0')}
          </span>
          <button
            onClick={stopRecording}
            className="ml-auto bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[13px]"
          >
            Parar
          </button>
        </div>
      ) : (
        <div className="border-t border-[#dedbd6] bg-[#faf9f6] p-3 flex gap-2 flex-shrink-0">
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,image/*"
            onChange={handleFileSelect}
            className="hidden"
          />
          <button
            onClick={startRecording}
            disabled={isInputBlocked}
            title="Gravar áudio"
            className="text-[#7b7b78] hover:text-[#111111] disabled:opacity-40 flex-shrink-0 self-end pb-[9px]"
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
            title="Anexar áudio ou imagem"
            className="text-[#7b7b78] hover:text-[#111111] disabled:opacity-40 flex-shrink-0 self-end pb-[9px]"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 1 0 2.828 2.828l6.414-6.586a4 4 0 0 0-5.656-5.656l-6.415 6.585a6 6 0 1 0 8.486 8.486L20.5 13" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digitar mensagem..."
            rows={1}
            className="flex-1 bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none resize-none max-h-32"
          />
          <button
            onClick={handleSend}
            disabled={sending || !text.trim()}
            className="bg-[#111111] text-white px-4 py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 active:scale-[0.85] disabled:opacity-40 flex-shrink-0 self-end"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
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
    </div>
  );
}

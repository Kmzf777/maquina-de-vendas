"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Clock3, MessageCircleReply } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useCurrentRole } from "@/hooks/use-current-role";
import { useOverdueLeads, type OverdueLead } from "@/hooks/use-overdue-leads";
import { setActiveConversation, useActiveConversation } from "@/lib/active-conversation";
import { buildReminderQueue, formatWindowHour, SLA_REMINDER_MINUTES } from "@/lib/sla-reminder";
import { formatBusinessDuration } from "@/lib/business-hours";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

/** Popup de SLA: só para vendedor (admin acompanha pelo dashboard). */
export function SlaReminderPopup() {
  const { role, loading } = useCurrentRole();
  if (loading || role !== "vendedor") return null;
  return <SlaReminderQueue />;
}

function SlaReminderQueue() {
  const { leads } = useOverdueLeads({ targetMinutes: SLA_REMINDER_MINUTES });
  const pathname = usePathname();
  const router = useRouter();
  const active = useActiveConversation();

  // "Depois" vale só para a página atual: toda troca de rota reabre a fila inteira.
  // Os dispensados ficam presos ao pathname em que foram dispensados; em outra rota
  // o conjunto efetivo é vazio (derivado no render, sem setState em effect).
  const [dismissedState, setDismissedState] = useState<{ path: string; ids: ReadonlySet<string> }>(
    () => ({ path: pathname, ids: new Set() }),
  );
  const dismissed = useMemo<ReadonlySet<string>>(
    () => (dismissedState.path === pathname ? dismissedState.ids : new Set()),
    [dismissedState, pathname],
  );

  const queue = useMemo(() => buildReminderQueue(leads, dismissed, active), [leads, dismissed, active]);
  const current = queue[0] ?? null;
  const lastText = useLastCustomerMessage(current?.conversationId ?? null);

  function dismissCurrent() {
    if (!current) return;
    const id = current.conversationId;
    setDismissedState((prev) => ({
      path: pathname,
      ids: new Set(prev.path === pathname ? prev.ids : []).add(id),
    }));
  }

  function respond(lead: OverdueLead) {
    // Grava antes de navegar: evita o popup piscar até /conversas abrir a conversa.
    setActiveConversation({ conversationId: lead.conversationId, leadId: lead.leadId });
    router.push(`/conversas?lead_id=${lead.leadId}`);
  }

  if (!current) return null;

  const showPhone = !!current.leadPhone && current.leadPhone !== current.leadName;
  const initial = (current.leadName || current.leadPhone || "?").trim().charAt(0).toUpperCase();
  const waiting = queue.length - 1;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) dismissCurrent(); }}>
      <DialogContent
        key={current.conversationId}
        showCloseButton={false}
        className="sm:max-w-[420px] max-w-[calc(100%-2rem)] overflow-hidden p-0 gap-0 rounded-[12px] border-[#dedbd6] bg-[#faf9f6] text-[#111111] shadow-[0_24px_60px_-20px_rgba(17,17,17,0.35)]"
      >
        {/* Faixa de urgência: marca o popup como alerta de SLA, não um modal comum. */}
        <div aria-hidden className="h-[3px] w-full bg-[#ff5600]" />

        <div className="px-6 pt-5 pb-6">
          <DialogHeader className="mb-5 gap-3">
            <span className="inline-flex w-fit items-center gap-2 text-[11px] font-medium uppercase tracking-[0.08em] text-[#ff5600]">
              <span aria-hidden className="relative flex size-2">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-[#ff5600] opacity-60 motion-reduce:animate-none" />
                <span className="relative inline-flex size-2 rounded-full bg-[#ff5600]" />
              </span>
              SLA de atendimento
            </span>

            <DialogTitle className="text-[19px] font-medium leading-snug tracking-tight text-[#111111]">
              Lead sem resposta há{" "}
              <span className="tabular-nums text-[#ff5600]">
                {formatBusinessDuration(current.elapsedMinutes)}
              </span>
            </DialogTitle>

            <div className="flex items-center gap-3">
              <div
                aria-hidden
                className="flex size-9 shrink-0 items-center justify-center rounded-[8px] bg-[#111111] text-[13px] font-medium text-white"
              >
                {initial}
              </div>
              <DialogDescription className="min-w-0 flex flex-col text-left">
                <span className="truncate text-[14px] font-medium text-[#111111]">{current.leadName}</span>
                {showPhone && (
                  <span className="truncate text-[12px] tabular-nums text-[#7b7b78]">{current.leadPhone}</span>
                )}
              </DialogDescription>
            </div>
          </DialogHeader>

          {lastText && (
            <figure className="mb-4">
              <figcaption className="mb-1.5 text-[11px] font-medium uppercase tracking-[0.06em] text-[#7b7b78]">
                Última mensagem do cliente
              </figcaption>
              <blockquote className="rounded-[8px] rounded-tl-[2px] border border-[#dedbd6] bg-white px-3 py-2 text-[13px] leading-relaxed text-[#313130] line-clamp-3 break-words">
                {lastText}
              </blockquote>
            </figure>
          )}

          <div className="flex gap-2.5 rounded-[8px] border border-[#ffd6bd] bg-[#fff1e8] px-3 py-2.5">
            <Clock3 aria-hidden className="mt-[1px] size-4 shrink-0 text-[#ff5600]" strokeWidth={1.75} />
            <p className="text-[13px] leading-relaxed text-[#111111]">
              Lembre-se: seu horário de atendimento é das{" "}
              <strong className="font-semibold tabular-nums">{formatWindowHour(current.windowStartMin)}</strong> às{" "}
              <strong className="font-semibold tabular-nums">{formatWindowHour(current.windowEndMin)}</strong>. Responda os leads dentro desse horário.
            </p>
          </div>

          <DialogFooter className="mt-6 flex-row items-center justify-between gap-3">
            <p className="text-[12px] text-[#7b7b78] tabular-nums">
              {waiting > 0 ? `+${waiting} lead(s) aguardando resposta` : ""}
            </p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={dismissCurrent}
                className="h-9 rounded-[8px] border border-[#dedbd6] bg-transparent px-4 text-[13px] text-[#313130] transition-colors hover:bg-[#f0ede8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#dedbd6]"
              >
                Depois
              </button>
              <button
                type="button"
                onClick={() => respond(current)}
                autoFocus
                className="inline-flex h-9 items-center gap-1.5 rounded-[8px] bg-[#ff5600] px-4 text-[13px] font-medium text-white transition-colors hover:bg-[#e64d00] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ff5600]/40 focus-visible:ring-offset-2 focus-visible:ring-offset-[#faf9f6]"
              >
                <MessageCircleReply aria-hidden className="size-4" strokeWidth={1.75} />
                Responder agora
              </button>
            </div>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Última mensagem do cliente na conversa (1 query por popup exibido). Falha = null. */
function useLastCustomerMessage(conversationId: string | null): string | null {
  const [state, setState] = useState<{ id: string; text: string | null } | null>(null);
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    const supabase = createClient();
    supabase
      .from("messages")
      .select("content")
      .eq("conversation_id", conversationId)
      .eq("sent_by", "user")
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle()
      .then(({ data }) => {
        if (!cancelled) setState({ id: conversationId, text: (data?.content as string | null) || null });
      }, () => { /* sem trecho: o popup abre mesmo assim */ });
    return () => { cancelled = true; };
  }, [conversationId]);
  return state && state.id === conversationId ? state.text : null;
}

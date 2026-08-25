"use client";

/**
 * Modal de orçamento — monta uma **proposta comercial no Bling** e a grava em
 * `quotes` + `quote_items`.
 *
 * Reaproveita, inteiros, os dois blocos que o registro de venda já resolveu:
 *
 * - `BlingOrderForm` — busca no catálogo, linhas de item, quantidade, valor,
 *   desconto por item, forma de pagamento e prazos. Recriar essa montagem aqui
 *   criaria dois formulários de item para manter, e o segundo divergiria do
 *   primeiro na primeira correção de bug.
 * - `BlingContactResolver` — o 409 de contato não resolvido, que a proposta
 *   comercial devolve no mesmo formato do pedido de venda.
 *
 * O que é novo é só o que o orçamento tem a mais que o pedido: desconto de
 * cabeçalho (R$ ou %), frete com modalidade, o par observação/observação
 * interna, e o resumo com o total e as parcelas.
 *
 * Todo cálculo vem de `buildQuotePayload` (`@/lib/quote-state`) e toda decisão
 * que pode dar errado vem de `@/lib/quote-modal-state` — ambos testados. Aqui
 * só há estado de tela e formatação.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckIcon, ChevronDownIcon, DownloadIcon } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BlingOrderForm } from "@/components/sales/bling-order-form";
import {
  BlingContactResolver,
  type BlingContactCandidate,
} from "@/components/sales/bling-contact-resolver";
import { useBlingStatus } from "@/hooks/use-bling-status";
import { blingGate } from "@/lib/bling-gate";
import { leadMatchesSearch } from "@/lib/search";
import type { OrderPayloadResult } from "@/lib/bling-order-state";
import { buildQuotePayload, linesFromQuoteItems } from "@/lib/quote-state";
import {
  FREIGHT_MODES,
  discountFromQuote,
  linesFromOrderPayload,
  parseDecimalInput,
  quoteOwner,
  quotePdfHref,
  quoteRequest,
  quoteSaveOutcome,
} from "@/lib/quote-modal-state";
import type { Quote } from "@/lib/types";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}

interface LeadOption {
  id: string;
  name: string | null;
  phone: string;
}

interface QuoteCreateModalProps {
  leadId?: string;
  /** `true` quando aberto de `/orcamento`, sem lead escolhido ainda. */
  pickLead?: boolean;
  lockedDealId?: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  editingQuote?: Quote | null;
  onClose: () => void;
  onSaved: () => void;
}

interface ContactResolution {
  status: "ambiguous" | "suggested" | "missing";
  reason?: string;
  candidates: BlingContactCandidate[];
}

const label = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1";
const field =
  "w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0";
const textarea =
  "w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0 resize-none min-h-0";
const trigger =
  "w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0";

const brl = (valor: number) =>
  valor.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

/** "2026-09-17" -> "17/09/2026", sem passar por Date (fuso não altera o dia). */
const diaMesAno = (iso: string) =>
  `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

/** Valor do `Select` que representa "não informar" — `null` no payload. */
const NENHUM = "__none__";

export function QuoteCreateModal({
  leadId,
  pickLead,
  lockedDealId,
  conversationId,
  currentUserEmail,
  editingQuote,
  onClose,
  onSaved,
}: QuoteCreateModalProps) {
  const isEditing = !!editingQuote;
  // Um orçamento convertido em venda não aceita mais edição (decisão 1 da
  // spec). O backend garante isso com 409, mas conferir aqui evita abrir um
  // formulário inteiro para uma gravação que já se sabe que vai ser recusada.
  const [convertido, setConvertido] = useState(
    editingQuote?.status === "convertido",
  );

  const blingStatus = useBlingStatus();
  // Sem escapatória "registrar só no CRM", ao contrário da venda: um orçamento
  // É a proposta comercial no Bling. Sem ela não há número, não há PDF e não há
  // o que converter em pedido depois — guardar a linha só no CRM criaria um
  // documento que promete um PDF que nunca vai existir.
  const gate = blingGate({
    loading: blingStatus.loading,
    error: blingStatus.error,
    enabled: blingStatus.enabled,
    isEditing,
  });
  // `blingGate` devolve "legacy" (com `canSubmit`) quando a integração está
  // desligada, porque para a VENDA isso é um caminho válido. Aqui não é.
  const podeEnviar = gate.mode === "bling";

  const [selectedLeadId, setSelectedLeadId] = useState(
    editingQuote?.lead_id ?? leadId ?? "",
  );
  const resolvedLeadId = selectedLeadId || leadId || "";

  const [dealId, setDealId] = useState(
    lockedDealId ?? editingQuote?.deal_id ?? "",
  );
  const [quotedAt, setQuotedAt] = useState(
    (editingQuote?.quoted_at ?? new Date().toISOString()).slice(0, 10),
  );

  // Desconto de cabeçalho: o TEXTO fica no estado, não o número. "0," e "1,"
  // são estados legítimos no meio da digitação e viram 0 no parse — guardar só
  // o número limparia o campo enquanto o vendedor ainda está digitando.
  const [descontoTexto, setDescontoTexto] = useState(() => {
    const d = discountFromQuote(editingQuote);
    return d ? String(d.valor) : "";
  });
  const [descontoUnidade, setDescontoUnidade] = useState<"REAL" | "PERCENTUAL">(
    () => discountFromQuote(editingQuote)?.unidade ?? "REAL",
  );
  const [freteTexto, setFreteTexto] = useState(
    editingQuote?.freight ? String(editingQuote.freight) : "",
  );
  const [freteModalidade, setFreteModalidade] = useState<number | null>(
    editingQuote?.freight_mode ?? null,
  );

  const [notes, setNotes] = useState(editingQuote?.notes ?? "");
  const [internalNotes, setInternalNotes] = useState(
    editingQuote?.internal_notes ?? "",
  );

  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [leadPickerOpen, setLeadPickerOpen] = useState(false);
  const [leadQuery, setLeadQuery] = useState("");
  const [deals, setDeals] = useState<LeadDeal[]>([]);

  const [orderResult, setOrderResult] = useState<OrderPayloadResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolution, setResolution] = useState<ContactResolution | null>(null);
  const [sucesso, setSucesso] = useState<{
    id: string | null;
    numero: number | null;
  } | null>(null);
  // O corpo já enviado, para a retentativa depois do 409 de contato reenviar
  // exatamente o mesmo orçamento em vez de remontá-lo.
  const enviadoRef = useRef<Record<string, unknown> | null>(null);

  // ── dados auxiliares ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!pickLead || isEditing) return;
    fetch("/api/leads")
      .then((r) => r.json())
      .then((d) => setLeads(Array.isArray(d) ? d : (d?.data ?? [])))
      .catch(() => undefined);
  }, [pickLead, isEditing]);

  useEffect(() => {
    if (lockedDealId || !resolvedLeadId) return;
    fetch(`/api/leads/${resolvedLeadId}/deals`)
      .then((r) => r.json())
      .then((d) =>
        setDeals(
          (Array.isArray(d) ? d : []).filter(
            (x: LeadDeal) => !x.pipeline_stages?.is_protected,
          ),
        ),
      )
      .catch(() => undefined);
  }, [resolvedLeadId, lockedDealId]);

  // ── números do orçamento ─────────────────────────────────────────────────
  const desconto = parseDecimalInput(descontoTexto);
  const frete = parseDecimalInput(freteTexto);
  const linhas = useMemo(
    () => linesFromOrderPayload(orderResult),
    [orderResult],
  );
  const pagamento = orderResult?.payload.payment;
  const methodId = pagamento?.method_id ?? null;
  const terms = useMemo(() => pagamento?.terms ?? [0], [pagamento?.terms]);

  const resultado = useMemo(
    () =>
      buildQuotePayload(linhas, {
        leadId: resolvedLeadId,
        dealId: lockedDealId ?? (dealId || null),
        conversationId: conversationId ?? null,
        quotedAt,
        // Derivado da prop a cada render, nunca copiado para estado no mount:
        // `currentUserEmail` chega de forma assíncrona (`useCurrentUserEmail`),
        // e um estado inicializado com "" ficaria congelado — o orçamento
        // nasceria sem dono e sumiria da tela de quem acabou de criá-lo, que é
        // exatamente o defeito corrigido no registro de venda em 24/08/2026.
        // Na edição `quoteOwner` preserva o criador (ver a função).
        createdBy: quoteOwner(editingQuote, currentUserEmail),
        discount: desconto > 0 ? { valor: desconto, unidade: descontoUnidade } : null,
        freight: frete,
        freightMode: freteModalidade,
        paymentMethodId: methodId,
        terms,
        notes: notes.trim(),
        internalNotes: internalNotes.trim(),
      }),
    [
      linhas,
      resolvedLeadId,
      lockedDealId,
      dealId,
      conversationId,
      quotedAt,
      editingQuote,
      currentUserEmail,
      desconto,
      descontoUnidade,
      frete,
      freteModalidade,
      methodId,
      terms,
      notes,
      internalNotes,
    ],
  );

  // O total não fecha em parcelas inteiras (só acontece em totais irrisórios,
  // mas o backend recusaria com 422 e o vendedor não entenderia por quê).
  const semParcela = resultado.total > 0 && resultado.installments.length === 0;

  // ── gravação ─────────────────────────────────────────────────────────────
  const enviar = useCallback(
    async (corpo: Record<string, unknown>) => {
      enviadoRef.current = corpo;
      setSaving(true);
      setError(null);

      const { url, method } = quoteRequest(editingQuote);
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo),
      }).catch(() => null);
      const body: Record<string, unknown> = res
        ? await res.json().catch(() => ({}))
        : {};
      setSaving(false);

      if (!res) {
        setError("Não foi possível falar com o servidor. Tente de novo.");
        return;
      }

      const desfecho = quoteSaveOutcome(res.status, body);
      if (desfecho.kind === "contact") {
        // Nada foi criado — nem contato, nem orçamento. O formulário continua
        // montado (só escondido) para o vendedor não perder o que digitou.
        setResolution({
          status: desfecho.status,
          reason: desfecho.reason,
          candidates: desfecho.candidates,
        });
        return;
      }
      if (desfecho.kind === "converted") {
        setConvertido(true);
        return;
      }
      if (desfecho.kind === "error") {
        setError(desfecho.message);
        return;
      }

      setResolution(null);
      if (isEditing) {
        onSaved();
        onClose();
        return;
      }
      // Na criação o `onSaved` fica para o "Concluir": nos chamadores ele
      // desmonta o modal, e o número da proposta — a informação que o vendedor
      // veio buscar, e o que nomeia o PDF — sumiria antes de ser lido.
      setSucesso({ id: desfecho.id, numero: desfecho.numero });
    },
    [editingQuote, isEditing, onSaved, onClose],
  );

  const retryAfterContact = useCallback(() => {
    setResolution(null);
    if (enviadoRef.current) void enviar(enviadoRef.current);
  }, [enviar]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (resolution || sucesso || convertido) return;
    if (!resolvedLeadId) {
      setError("Selecione o lead");
      return;
    }
    if (!resultado.valid) {
      setError(
        "Escolha ao menos um produto com quantidade e a forma de pagamento",
      );
      return;
    }
    if (semParcela) {
      setError(
        "O total não fecha nas parcelas escolhidas — ajuste os prazos ou os itens.",
      );
      return;
    }
    await enviar(resultado.payload);
  }

  /** Fecha avisando o chamador quando algo já foi gravado (recarrega a lista). */
  function fecharModal() {
    if (sucesso) onSaved();
    onClose();
  }

  const leadSelecionado = leads.find((l) => l.id === resolvedLeadId);
  const escondeFormulario = !!resolution || !!sucesso || convertido;

  return (
    <Dialog open onOpenChange={(open) => { if (!open) fecharModal(); }}>
      <DialogContent
        showCloseButton={false}
        className="bg-white border border-[#dedbd6] rounded-[8px] p-0 w-full max-w-4xl max-h-[90vh] overflow-y-auto shadow-lg gap-0"
      >
        <DialogHeader className="flex-row items-center justify-between px-5 py-4 border-b border-[#dedbd6] mb-0 gap-0">
          <DialogTitle className="text-[15px] font-medium text-[#111111]">
            {isEditing ? "Editar Orçamento" : "Novo Orçamento"}
          </DialogTitle>
          <button
            type="button"
            onClick={fecharModal}
            aria-label="Fechar"
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </DialogHeader>

        {/* O formulário fica montado (só escondido) durante o resolvedor de
            contato: desmontá-lo perderia o orçamento inteiro já digitado. */}
        <form
          onSubmit={handleSubmit}
          className={`p-5 ${escondeFormulario ? "hidden" : ""}`}
        >
          {gate.mode === "loading" ? (
            <p className="py-10 text-center text-[13px] text-[#7b7b78]">
              Verificando conexão com o Bling…
            </p>
          ) : gate.mode === "legacy" ? (
            <p className="py-10 text-center text-[13px] text-[#7b7b78]">
              A integração com o Bling está desligada. O orçamento é criado como
              proposta comercial no Bling — sem a integração não há número nem
              PDF para enviar ao cliente.
            </p>
          ) : (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_268px] lg:items-start">
              {/* ── coluna do documento ─────────────────────────────────── */}
              <div className="space-y-4 min-w-0">
                {pickLead && !isEditing && (
                  <div>
                    <label className={label}>Lead *</label>
                    <Popover open={leadPickerOpen} onOpenChange={setLeadPickerOpen}>
                      <PopoverTrigger asChild>
                        <button
                          type="button"
                          className="flex w-full h-[37px] items-center justify-between bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                        >
                          <span className={resolvedLeadId ? "truncate" : "text-[#8a8a8a]"}>
                            {resolvedLeadId
                              ? (leadSelecionado?.name ??
                                 leadSelecionado?.phone ??
                                 "Lead selecionado")
                              : "Selecione o lead"}
                          </span>
                          <ChevronDownIcon className="size-4 shrink-0 text-[#8a8a8a]" />
                        </button>
                      </PopoverTrigger>
                      <PopoverContent className="p-0" portal={false}>
                        <div className="p-2 border-b border-[#eee]">
                          <Input
                            autoFocus
                            value={leadQuery}
                            onChange={(e) => setLeadQuery(e.target.value)}
                            placeholder="Buscar lead por nome ou telefone..."
                            className="h-8 text-[14px]"
                          />
                        </div>
                        <div className="max-h-64 overflow-y-auto p-1">
                          {leads.filter((l) => leadMatchesSearch(leadQuery, l)).length === 0 && (
                            <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">
                              Nenhum lead encontrado.
                            </div>
                          )}
                          {leads
                            .filter((l) => leadMatchesSearch(leadQuery, l))
                            .slice(0, 100)
                            .map((l) => (
                              <button
                                key={l.id}
                                type="button"
                                onClick={() => {
                                  setSelectedLeadId(l.id);
                                  setDealId("");
                                  setLeadPickerOpen(false);
                                  setLeadQuery("");
                                }}
                                className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[14px] hover:bg-[#f4f2ee]"
                              >
                                <span className="truncate">{l.name ?? l.phone}</span>
                                {resolvedLeadId === l.id && <CheckIcon className="size-4 shrink-0" />}
                              </button>
                            ))}
                        </div>
                      </PopoverContent>
                    </Popover>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={label}>Data do orçamento</label>
                    <Input
                      type="date"
                      value={quotedAt}
                      onChange={(e) => setQuotedAt(e.target.value)}
                      className={field}
                    />
                  </div>
                  {!lockedDealId && (
                    <div>
                      <label className={label}>Oportunidade</label>
                      <Select
                        value={dealId || NENHUM}
                        onValueChange={(v) => setDealId(v === NENHUM ? "" : v)}
                      >
                        <SelectTrigger className={trigger}>
                          <SelectValue placeholder="Não vincular" />
                        </SelectTrigger>
                        <SelectContent position="popper">
                          <SelectItem value={NENHUM}>Não vincular</SelectItem>
                          {deals.map((d) => (
                            <SelectItem key={d.id} value={d.id}>
                              {d.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {dealId && (
                        <p className="mt-1 text-[11px] text-[#7b7b78]">
                          O card vai para “Proposta Enviada”.
                        </p>
                      )}
                    </div>
                  )}
                </div>

                <BlingOrderForm
                  meta={{
                    leadId: resolvedLeadId,
                    dealId: lockedDealId ?? (dealId || null),
                    soldAt: quotedAt,
                    soldBy: currentUserEmail || null,
                    notes: notes.trim(),
                  }}
                  condicaoPagamento={editingQuote?.payment_terms ?? null}
                  // Editar SEM isto apagaria os itens da proposta no Bling: o
                  // PUT substitui os itens pelo que estiver no formulário, e um
                  // formulário que nasce com uma linha em branco manda uma
                  // linha em branco. Mesmo defeito já visto em `sale_items`.
                  initialLines={
                    isEditing ? linesFromQuoteItems(editingQuote?.quote_items) : undefined
                  }
                  initialPaymentMethodId={editingQuote?.payment_method_id ?? null}
                  // O resumo à direita é a única fonte do total e das parcelas —
                  // aqui elas ainda não conhecem desconto de cabeçalho e frete.
                  showInstallments={false}
                  onChange={setOrderResult}
                />

                {/* Desconto do orçamento e frete */}
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label className={label}>Desconto no total</label>
                    <div className="flex">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={descontoTexto}
                        onChange={(e) => setDescontoTexto(e.target.value)}
                        placeholder="0"
                        aria-label="Desconto no total do orçamento"
                        className={`${field} rounded-r-none tabular-nums`}
                      />
                      {/* Alternador R$ / % — dois estados, sempre visíveis: um
                          select esconderia a unidade atrás de um clique, e é
                          ela que muda o significado do número ao lado. */}
                      {(["REAL", "PERCENTUAL"] as const).map((u) => (
                        <button
                          key={u}
                          type="button"
                          onClick={() => setDescontoUnidade(u)}
                          aria-pressed={descontoUnidade === u}
                          className={`h-[37px] w-10 shrink-0 -ml-px text-[13px] border transition-colors last:rounded-r-[4px] ${
                            descontoUnidade === u
                              ? "bg-[#111111] border-[#111111] text-white"
                              : "bg-white border-[#dedbd6] text-[#7b7b78] hover:text-[#111111]"
                          }`}
                        >
                          {u === "REAL" ? "R$" : "%"}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className={label}>Frete (R$)</label>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={freteTexto}
                      onChange={(e) => setFreteTexto(e.target.value)}
                      placeholder="0,00"
                      aria-label="Valor do frete"
                      className={`${field} tabular-nums`}
                    />
                  </div>
                </div>

                <div>
                  <label className={label}>Modalidade do frete</label>
                  <Select
                    value={freteModalidade === null ? NENHUM : String(freteModalidade)}
                    onValueChange={(v) =>
                      setFreteModalidade(v === NENHUM ? null : Number(v))
                    }
                  >
                    <SelectTrigger className={trigger}>
                      <SelectValue placeholder="Não informar" />
                    </SelectTrigger>
                    <SelectContent position="popper">
                      <SelectItem value={NENHUM}>Não informar</SelectItem>
                      {FREIGHT_MODES.map((m) => (
                        <SelectItem key={m.value} value={String(m.value)}>
                          {m.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <label className={label}>Observações</label>
                  <Textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={2}
                    placeholder="Condições combinadas, prazo de entrega, referências..."
                    className={textarea}
                  />
                  <p className="mt-1 text-[11px] text-[#7b7b78]">
                    Sai no PDF que o cliente recebe e vai junto para o Bling.
                  </p>
                </div>

                <div>
                  <label className={label}>Observação interna</label>
                  <Textarea
                    value={internalNotes}
                    onChange={(e) => setInternalNotes(e.target.value)}
                    rows={2}
                    placeholder="Margem, histórico da negociação, alerta para o financeiro..."
                    className={textarea}
                  />
                  <p className="mt-1 text-[11px] text-[#7b7b78]">
                    Fica só no Bling.{" "}
                    <strong className="font-medium text-[#111111]">
                      Não sai no PDF
                    </strong>{" "}
                    que o cliente recebe.
                  </p>
                </div>
              </div>

              {/* ── resumo ──────────────────────────────────────────────── */}
              <aside className="lg:sticky lg:top-0 space-y-4">
                <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] px-4 py-3">
                  <span className={label}>Resumo</span>

                  <dl className="space-y-1.5">
                    <div className="flex items-baseline justify-between gap-3 text-[13px] tabular-nums">
                      <dt className="text-[#7b7b78]">Subtotal dos itens</dt>
                      <dd className="text-[#111111]">R$ {brl(resultado.subtotal)}</dd>
                    </div>
                    {/* Desconto e frete só aparecem quando existem — uma linha
                        de "R$ 0,00" é ruído num resumo de quatro linhas. */}
                    {resultado.discount > 0 && (
                      <div className="flex items-baseline justify-between gap-3 text-[13px] tabular-nums">
                        <dt className="text-[#7b7b78]">
                          Desconto
                          {descontoUnidade === "PERCENTUAL" && desconto > 0 && (
                            <span className="ml-1 text-[11px]">({brl(desconto)}%)</span>
                          )}
                        </dt>
                        <dd className="text-[#c41c1c]">− R$ {brl(resultado.discount)}</dd>
                      </div>
                    )}
                    {resultado.freight > 0 && (
                      <div className="flex items-baseline justify-between gap-3 text-[13px] tabular-nums">
                        <dt className="text-[#7b7b78]">Frete</dt>
                        <dd className="text-[#111111]">R$ {brl(resultado.freight)}</dd>
                      </div>
                    )}
                  </dl>

                  <div className="mt-2.5 pt-2.5 border-t border-[#dedbd6] flex items-baseline justify-between gap-3">
                    <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
                      Total
                    </span>
                    <span className="text-[22px] leading-none tracking-[-0.48px] text-[#111111] tabular-nums">
                      R$ {brl(resultado.total)}
                    </span>
                  </div>
                </div>

                <div className="border border-[#dedbd6] rounded-[8px] px-4 py-3">
                  <span className={label}>
                    {resultado.installments.length === 1
                      ? "Parcela"
                      : `${resultado.installments.length || ""} Parcelas`.trim()}
                  </span>
                  {semParcela ? (
                    <p className="text-[12px] text-[#c41c1c]">
                      Não é possível dividir R$ {brl(resultado.total)} em{" "}
                      {terms.length} parcelas — alguma ficaria sem valor.
                    </p>
                  ) : resultado.installments.length === 0 ? (
                    <p className="text-[12px] text-[#7b7b78]">
                      Escolha os itens e a forma de pagamento para ver as parcelas.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {resultado.installments.map((p, i) => (
                        <li
                          key={i}
                          className="flex items-center justify-between text-[13px] text-[#111111] tabular-nums"
                        >
                          <span className="text-[#7b7b78]">
                            {i + 1}ª · {diaMesAno(p.dataVencimento)}
                          </span>
                          <span>R$ {brl(p.valor)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </aside>
            </div>
          )}

          {error && <p className="mt-4 text-[12px] text-[#c41c1c]">{error}</p>}
          {gate.message && (
            <p className="mt-4 text-[12px] text-[#c41c1c]">{gate.message}</p>
          )}
          {podeEnviar && !error && !resultado.valid && (
            <p className="mt-4 text-[11px] text-[#7b7b78]">
              Escolha ao menos um produto com quantidade e a forma de pagamento
              para gerar o orçamento.
            </p>
          )}

          <div className="flex gap-2 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving || !podeEnviar || !resultado.valid}
              className="flex-1 py-2 text-[13px] font-medium text-white rounded-[4px] transition-colors bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78]"
            >
              {saving
                ? "Salvando..."
                : isEditing
                  ? "Salvar orçamento"
                  : "Gerar orçamento"}
            </button>
          </div>
        </form>

        {/* 409 de contato — quem decide qual é o cliente no Bling é o vendedor */}
        {resolution && (
          <div className="p-5">
            <BlingContactResolver
              leadId={resolvedLeadId}
              status={resolution.status}
              reason={resolution.reason}
              candidates={resolution.candidates}
              defaults={{
                nome: leadSelecionado?.name ?? "",
                telefone: leadSelecionado?.phone ?? "",
              }}
              onResolved={retryAfterContact}
              onCancel={() => setResolution(null)}
            />
          </div>
        )}

        {/* 409 de orçamento já convertido — não há o que salvar, só informar */}
        {convertido && !resolution && (
          <div className="p-5 space-y-3">
            <p className="text-[14px] text-[#111111]">
              Este orçamento já foi convertido em venda.
            </p>
            <p className="text-[12px] text-[#7b7b78]">
              Depois da conversão o documento fica congelado nos dois lados —
              alterar aqui deixaria o CRM diferente do pedido que já existe no
              Bling. Para mudar algo, registre a alteração na venda.
            </p>
            <button
              type="button"
              onClick={fecharModal}
              className="w-full py-2 text-[13px] text-[#111111] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
            >
              Fechar
            </button>
          </div>
        )}

        {/* Criado — o número da proposta e o PDF são o que o vendedor procura */}
        {sucesso && (
          <div className="p-5 text-center space-y-3">
            <div className="mx-auto w-10 h-10 rounded-full bg-[#1f9d57]/10 flex items-center justify-center">
              <CheckIcon className="size-5 text-[#1f9d57]" />
            </div>
            <p className="text-[15px] text-[#111111]">
              {sucesso.numero
                ? `Orçamento #${sucesso.numero} criado no Bling`
                : "Orçamento criado no Bling"}
            </p>
            <p className="text-[12px] text-[#7b7b78]">
              A proposta nasce como rascunho no ERP. O PDF já pode ser baixado e
              enviado ao cliente.
            </p>
            <div className="flex gap-2 pt-1">
              {sucesso.id && (
                <a
                  href={quotePdfHref(sucesso.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex-1 inline-flex items-center justify-center gap-1.5 py-2 text-[13px] text-[#111111] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
                >
                  <DownloadIcon className="size-3.5" />
                  Baixar PDF
                </a>
              )}
              <button
                type="button"
                onClick={fecharModal}
                className="flex-1 py-2 text-[13px] font-medium text-white rounded-[4px] bg-[#1f9d57] hover:bg-[#1b8a4c] transition-colors"
              >
                Concluir
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

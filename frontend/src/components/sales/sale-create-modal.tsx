"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { TeamUser, Sale } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { leadMatchesSearch } from "@/lib/search";
import { ChevronDownIcon, CheckIcon } from "lucide-react";
import { BlingOrderForm } from "@/components/sales/bling-order-form";
import {
  BlingContactResolver,
  type BlingContactCandidate,
} from "@/components/sales/bling-contact-resolver";
import {
  linesFromSaleItems,
  type OrderPayloadResult,
} from "@/lib/bling-order-state";
import { useBlingStatus } from "@/hooks/use-bling-status";
import { blingGate } from "@/lib/bling-gate";
import { productSummary } from "@/lib/bling";
import { divergenceFrom, type Divergence } from "@/lib/bling-divergence";

interface LeadDeal {
  id: string;
  title: string;
  pipeline_stages?: { is_protected: boolean } | null;
}

interface Pipeline {
  id: string;
  name: string;
}

interface LeadOption {
  id: string;
  name: string | null;
  phone: string;
}

interface SaleCreateModalProps {
  leadId?: string;
  pickLead?: boolean;
  lockedDealId?: string;
  lockedDealTitle?: string;
  conversationId?: string | null;
  currentUserEmail?: string;
  editingSale?: Sale | null;
  /**
   * Força o modo Bling, no qual o pedido é montado com itens do catálogo e
   * lançado no ERP em vez de gravar produto em texto livre.
   *
   * **Omitir é o normal:** sem a prop, o modal consulta `/api/bling/status`
   * pelo `useBlingStatus` e decide sozinho. Informar a prop VENCE a consulta —
   * serve para forçar o modo sem depender de rede, não para uso corriqueiro.
   *
   * Cuidado: até 21/08/2026 omitir significava "modo legado", e como nenhum dos
   * quatro chamadores passava a prop, o modo Bling era inalcançável em produção.
   */
  blingEnabled?: boolean;
  /** `condicao_pagamento` do contato no Bling, quando quem abre o modal a conhece. */
  blingCondicaoPagamento?: string | null;
  onClose: () => void;
  onSaved: () => void;
}

interface ContactResolution {
  status: "ambiguous" | "suggested" | "missing";
  reason?: string;
  candidates: BlingContactCandidate[];
}

const fieldLabel = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1";
const fieldInput =
  "w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0";

export function SaleCreateModal({
  leadId,
  pickLead,
  lockedDealId,
  lockedDealTitle,
  conversationId,
  currentUserEmail,
  editingSale,
  blingEnabled,
  blingCondicaoPagamento,
  onClose,
  onSaved,
}: SaleCreateModalProps) {
  const isEditing = !!editingSale;
  // Editar venda com o Bling ligado agora dá PUT no pedido do ERP (Fase E) —
  // ver `blingMode` abaixo, que também exige que a venda tenha um pedido
  // (`bling_order_id`) para ter o que alterar.
  const blingStatus = useBlingStatus();
  const gate = blingGate({
    loading: blingStatus.loading,
    error: blingStatus.error,
    // A prop continua existindo e VENCE quando informada: quem quiser forcar o
    // modo (teste, chamador especifico) nao passa a depender de rede.
    enabled: blingEnabled ?? blingStatus.enabled,
    isEditing,
  });
  // Editar exige mais que o Bling estar ligado: só faz sentido dar PUT numa
  // venda que já tem pedido no ERP. Vendas de antes desta integração (ou
  // registradas em modo legado) não têm `bling_order_id` — continuam editando
  // local mesmo com o Bling ligado, porque não há pedido para alterar.
  const blingEditable = !isEditing || !!editingSale?.bling_order_id;
  const blingMode = gate.mode === "bling" && blingEditable;
  // Layout: `loading` ainda nao sabe o modo, mas abrir pequeno e pular para
  // grande quando o status chega e pior do que abrir grande. Tratar loading
  // como Bling aqui evita o salto de tamanho.
  const blingLayout = (gate.mode === "bling" || gate.mode === "loading") && blingEditable;

  const [selectedLeadId, setSelectedLeadId] = useState(
    editingSale?.lead_id ?? leadId ?? ""
  );
  const [product, setProduct] = useState(editingSale?.product ?? "");
  const [value, setValue] = useState(
    editingSale ? String(editingSale.value) : ""
  );
  const [soldAt, setSoldAt] = useState(
    (editingSale?.sold_at ?? new Date().toISOString()).slice(0, 10)
  );
  const [soldBy, setSoldBy] = useState(
    editingSale?.sold_by ?? currentUserEmail ?? ""
  );
  const [dealId, setDealId] = useState(lockedDealId ?? "");
  const [creatingDeal, setCreatingDeal] = useState(false);
  const [newDealTitle, setNewDealTitle] = useState("");
  const [newDealPipeline, setNewDealPipeline] = useState("");
  const [notes, setNotes] = useState(editingSale?.notes ?? "");

  const [leadPickerOpen, setLeadPickerOpen] = useState(false);
  const [leadQuery, setLeadQuery] = useState("");

  const [users, setUsers] = useState<TeamUser[]>([]);
  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [deals, setDeals] = useState<LeadDeal[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── modo Bling ───────────────────────────────────────────────────────────
  const [orderResult, setOrderResult] = useState<OrderPayloadResult | null>(null);
  const [resolution, setResolution] = useState<ContactResolution | null>(null);
  const [sucesso, setSucesso] = useState<{ titulo: string; detalhe: string } | null>(
    null
  );
  // Deal criado inline numa tentativa anterior: sem guardar o id, cada retentativa
  // depois do 409 criaria um deal novo para a mesma venda.
  const [createdDealId, setCreatedDealId] = useState<string | null>(null);
  const orderPayloadRef = useRef<Record<string, unknown> | null>(null);

  // ── edição em modo Bling (PUT no pedido) ────────────────────────────────
  // 422: o Bling recusou a alteração. Fica pendente até o vendedor decidir —
  // "Salvar só no CRM" marca divergência; cancelar mantém o pedido como está
  // nos dois lados.
  const [pendingBlingUpdate, setPendingBlingUpdate] = useState<{
    message: string;
    payload: OrderPayloadResult["payload"];
    total: number;
  } | null>(null);

  // ── initial data fetches ─────────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/users")
      .then((r) => r.json())
      .then((d) => setUsers(Array.isArray(d) ? d : []));

    if (pickLead && !isEditing) {
      fetch("/api/leads")
        .then((r) => r.json())
        .then((d) => {
          const arr = Array.isArray(d) ? d : (d?.data ?? []);
          setLeads(arr);
        });
    }

    if (!isEditing && !lockedDealId) {
      fetch("/api/pipelines")
        .then((r) => r.json())
        .then((d) => setPipelines(Array.isArray(d) ? d : []));
    }
  }, [pickLead, isEditing, lockedDealId]);

  // ── fetch deals when selectedLeadId changes ──────────────────────────────
  useEffect(() => {
    if (isEditing || lockedDealId || !selectedLeadId) return;
    fetch(`/api/leads/${selectedLeadId}/deals`)
      .then((r) => r.json())
      .then((d) =>
        setDeals(
          (Array.isArray(d) ? d : []).filter(
            (x: LeadDeal) => !x.pipeline_stages?.is_protected
          )
        )
      );
  }, [selectedLeadId, isEditing, lockedDealId]);

  // ── pedido no Bling ──────────────────────────────────────────────────────
  /**
   * Posta em `/api/bling/orders` e trata os quatro desfechos do contrato:
   * 201 criado, 202 na fila, 409 contato não resolvido, 422 recusa do Bling.
   */
  const postBlingOrder = useCallback(
    async (payload: Record<string, unknown>) => {
      orderPayloadRef.current = payload;
      setSaving(true);
      setError(null);

      const res = await fetch("/api/bling/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => null);
      const body: Record<string, unknown> = res
        ? await res.json().catch(() => ({}))
        : {};
      setSaving(false);

      if (!res) {
        setError("Não foi possível falar com o servidor. Tente de novo.");
        return;
      }

      if (res.status === 201) {
        const numero = body.bling_order_number ?? body.bling_order_id;
        setResolution(null);
        // `onSaved` fica para o "Concluir": nos chamadores ele desmonta o modal,
        // e o número do pedido sumiria antes de o vendedor conseguir lê-lo.
        setSucesso({
          titulo: `Pedido #${numero} criado no Bling`,
          detalhe: "A venda também já está registrada no CRM.",
        });
        return;
      }

      if (res.status === 202) {
        setResolution(null);
        setSucesso({
          titulo: "Venda registrada",
          detalhe:
            "O pedido está sendo enviado ao Bling e aparece por lá assim que o ERP responder.",
        });
        return;
      }

      if (res.status === 409) {
        // O backend não chuta o contato: quem decide é o vendedor. Nada foi
        // criado — nem contato, nem venda —, então o formulário segue montado.
        const status = body.status;
        setResolution({
          status:
            status === "ambiguous" || status === "suggested" ? status : "missing",
          reason: typeof body.reason === "string" ? body.reason : undefined,
          candidates: Array.isArray(body.candidates)
            ? (body.candidates as BlingContactCandidate[])
            : [],
        });
        return;
      }

      if (res.status === 422) {
        // Mensagem original do Bling — é ela que diz o que corrigir.
        setError(
          [body.message, body.detail].filter(Boolean).join(" ") ||
            "O Bling recusou o pedido."
        );
        return;
      }

      setError(
        (body.message as string) ??
          (body.error as string) ??
          "Erro ao lançar o pedido no Bling"
      );
    },
    []
  );

  const retryAfterContact = useCallback(() => {
    setResolution(null);
    if (orderPayloadRef.current) void postBlingOrder(orderPayloadRef.current);
  }, [postBlingOrder]);

  /**
   * PATCH local que fecha a edição em modo Bling, tanto no caminho feliz (200,
   * sem divergência) quanto na decisão de "salvar só no CRM" (422, marcando
   * divergência). `product`/`value` vêm dos itens do pedido, não dos campos de
   * texto livre — esses ficam escondidos enquanto `blingMode` está ativo.
   */
  const saveLocalAfterBlingPut = useCallback(
    async (
      payload: OrderPayloadResult["payload"],
      total: number,
      divergencia: { bling_divergent: boolean; bling_divergence: Divergence | null }
    ) => {
      setSaving(true);
      setError(null);
      const res = await fetch(`/api/sales/${editingSale!.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: productSummary(payload.items),
          value: total,
          sold_at: new Date(soldAt + "T12:00:00").toISOString(),
          sold_by: soldBy && soldBy !== "__none__" ? soldBy : null,
          notes: notes.trim() || null,
          ...divergencia,
        }),
      });
      setSaving(false);
      if (!res.ok) {
        const msg = res.headers.get("content-type")?.includes("json")
          ? (await res.json().catch(() => ({}))).error
          : null;
        setError(msg ?? "Erro ao salvar venda");
        return;
      }
      onSaved();
      onClose();
    },
    [editingSale, soldAt, soldBy, notes, onSaved, onClose]
  );

  /**
   * PUT em `/api/bling/orders/{bling_order_id}` e trata os quatro desfechos:
   * 200 alterado (grava local, limpa divergência), 202 erro transitório (não
   * salva nada — é retentativa, não recusa), 409 contato não resolvido, 422
   * recusa de validação (fica pendente até o vendedor decidir).
   */
  const putBlingOrder = useCallback(
    async (payload: OrderPayloadResult["payload"], total: number) => {
      setSaving(true);
      setError(null);

      const orderId = editingSale?.bling_order_id;
      const res = await fetch(`/api/bling/orders/${orderId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => null);
      const body: Record<string, unknown> = res
        ? await res.json().catch(() => ({}))
        : {};
      setSaving(false);

      if (!res) {
        setError("Não foi possível falar com o servidor. Tente de novo.");
        return;
      }

      if (res.status === 200) {
        await saveLocalAfterBlingPut(payload, total, {
          bling_divergent: false,
          bling_divergence: null,
        });
        return;
      }

      if (res.status === 202) {
        // Erro TRANSITÓRIO: não é recusa, é retentativa. Não salva nada local
        // e não marca divergência — confundir os dois viraria ruído permanente.
        setError(
          "Bling indisponível no momento. Tente salvar de novo em instantes."
        );
        return;
      }

      if (res.status === 422) {
        // Mensagem original do Bling — é ela que diz por que recusou.
        const message =
          [body.message, body.detail].filter(Boolean).join(" ") ||
          "O Bling recusou a alteração.";
        setPendingBlingUpdate({ message, payload, total });
        return;
      }

      if (res.status === 409) {
        setError(
          (body.reason as string) ??
            "Não foi possível confirmar o contato vinculado no Bling."
        );
        return;
      }

      setError(
        (body.message as string) ??
          (body.error as string) ??
          "Erro ao atualizar o pedido no Bling"
      );
    },
    [editingSale, saveLocalAfterBlingPut]
  );

  /** "Salvar só no CRM" após o Bling recusar (422): grava local e marca divergência. */
  const confirmSaveLocalOnly = useCallback(async () => {
    if (!pendingBlingUpdate) return;
    const { payload, total } = pendingBlingUpdate;
    const divergencia = divergenceFrom(
      {
        value: editingSale!.value,
        product: editingSale!.product,
        notes: editingSale!.notes,
      },
      { value: total, product: productSummary(payload.items), notes: notes.trim() || null },
      new Date().toISOString()
    );
    setPendingBlingUpdate(null);
    await saveLocalAfterBlingPut(payload, total, {
      bling_divergent: true,
      bling_divergence: divergencia,
    });
  }, [pendingBlingUpdate, editingSale, notes, saveLocalAfterBlingPut]);

  // ── submit ───────────────────────────────────────────────────────────────
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (resolution || sucesso || pendingBlingUpdate) return;
    if (!blingMode && (!product.trim() || !value)) {
      setError("Produto e valor são obrigatórios");
      return;
    }

    if (isEditing) {
      // Bling ligado e venda com pedido no ERP: a edição vira PUT no pedido,
      // não PATCH direto — o Bling precisa aceitar a mudança primeiro.
      if (blingMode) {
        if (!orderResult?.valid) {
          setError(
            "Escolha ao menos um produto com quantidade e a forma de pagamento"
          );
          return;
        }
        await putBlingOrder(orderResult.payload, orderResult.total);
        return;
      }

      setSaving(true);
      setError(null);
      const res = await fetch(`/api/sales/${editingSale!.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product: product.trim(),
          value: parseFloat(value),
          sold_at: new Date(soldAt + "T12:00:00").toISOString(),
          sold_by: soldBy && soldBy !== "__none__" ? soldBy : null,
          notes: notes.trim() || null,
        }),
      });
      if (!res.ok) {
        const msg = res.headers.get("content-type")?.includes("json")
          ? (await res.json().catch(() => ({}))).error
          : null;
        setError(msg ?? "Erro ao salvar venda");
        setSaving(false);
        return;
      }
      onSaved();
      onClose();
      return;
    }

    if (!selectedLeadId) {
      setError("Selecione o lead");
      return;
    }

    const linkExisting = !!dealId && !creatingDeal;
    const linkNew =
      creatingDeal && !!newDealTitle.trim() && !!newDealPipeline;

    if (!lockedDealId && !linkExisting && !linkNew) {
      setError("Vincule a um deal existente ou crie um novo deal");
      return;
    }

    if (blingMode) {
      if (!orderResult?.valid) {
        setError(
          "Escolha ao menos um produto com quantidade e a forma de pagamento"
        );
        return;
      }

      // `/api/bling/orders` recebe `deal_id` pronto — o deal inline é criado
      // antes, e o id fica guardado para a retentativa não criar um segundo.
      let deal: string | null = lockedDealId ?? (linkExisting ? dealId : createdDealId);
      if (!deal && linkNew) {
        setSaving(true);
        setError(null);
        const criado = await fetch("/api/deals", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lead_id: selectedLeadId,
            title: newDealTitle.trim(),
            pipeline_id: newDealPipeline,
          }),
        }).catch(() => null);
        const corpo = criado ? await criado.json().catch(() => ({})) : {};
        if (!criado?.ok || !corpo?.id) {
          setError(corpo?.error ?? "Não foi possível criar o deal");
          setSaving(false);
          return;
        }
        deal = corpo.id as string;
        setCreatedDealId(deal);
      }

      // `conversation_id` não passa pelo `buildOrderPayload` (é do modal, não do
      // pedido), mas é a rastreabilidade que o caminho não-Bling já grava: quem
      // registra a venda a partir do chat vê a venda ligada ao atendimento que a
      // gerou. A retentativa pós-409 reenvia o payload inteiro, então herda o campo.
      await postBlingOrder({
        ...orderResult.payload,
        deal_id: deal ?? null,
        conversation_id: conversationId || null,
      });
      return;
    }

    setSaving(true);
    setError(null);

    const payload: Record<string, unknown> = {
      lead_id: selectedLeadId,
      conversation_id: conversationId || null,
      product: product.trim(),
      value: parseFloat(value),
      sold_at: new Date(soldAt + "T12:00:00").toISOString(),
      sold_by: soldBy && soldBy !== "__none__" ? soldBy : null,
      notes: notes.trim() || null,
    };

    if (lockedDealId) {
      payload.deal_id = lockedDealId;
    } else if (linkExisting) {
      payload.deal_id = dealId;
    } else {
      payload.new_deal = {
        title: newDealTitle.trim(),
        pipeline_id: newDealPipeline,
      };
    }

    const res = await fetch("/api/sales", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const msg = res.headers.get("content-type")?.includes("json")
        ? (await res.json().catch(() => ({}))).error
        : null;
      setError(msg ?? "Erro ao salvar venda");
      setSaving(false);
      return;
    }
    onSaved();
    onClose();
  }

  // ── helpers ───────────────────────────────────────────────────────────────
  const resolvedLeadId = selectedLeadId || leadId || "";
  // Só existe no modo `pickLead` (é a lista carregada para o combobox); serve
  // para pré-preencher o cadastro do contato e poupar digitação do vendedor.
  const leadSelecionado = leads.find((l) => l.id === resolvedLeadId);

  /** Fecha avisando o chamador quando o pedido já foi lançado (recarrega a lista). */
  function fecharModal() {
    if (sucesso) onSaved();
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) fecharModal(); }}>
      <DialogContent
        showCloseButton={false}
        className={`bg-white border border-[#dedbd6] rounded-[8px] p-0 w-full shadow-lg gap-0 ${
          blingLayout
            ? "max-w-2xl max-h-[88vh] overflow-y-auto"
            : "max-w-md"
        }`}
      >
        {/* Header */}
        <DialogHeader className="flex-row items-center justify-between px-5 py-4 border-b border-[#dedbd6] mb-0 gap-0">
          <DialogTitle className="text-[15px] font-medium text-[#111111]">
            {isEditing ? "Editar Venda" : "Registrar Venda"}
          </DialogTitle>
          <button
            type="button"
            onClick={fecharModal}
            aria-label="Fechar"
            className="w-7 h-7 flex items-center justify-center rounded-[4px] text-[#7b7b78] hover:bg-[#dedbd6]/60 transition-colors"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </DialogHeader>

        {/* Form — fica montado (só escondido) enquanto o resolvedor de contato
            aparece, senão o vendedor perderia o pedido inteiro que já digitou. */}
        <form
          onSubmit={handleSubmit}
          className={`p-5 space-y-4 ${resolution || sucesso || pendingBlingUpdate ? "hidden" : ""}`}
        >

          {/* Lead selector — searchable combobox, only in pickLead mode and not editing */}
          {pickLead && !isEditing && (
            <div>
              <label className={fieldLabel}>Lead *</label>
              <Popover open={leadPickerOpen} onOpenChange={setLeadPickerOpen}>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="flex w-full h-[37px] items-center justify-between bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
                  >
                    <span className={resolvedLeadId ? "" : "text-[#8a8a8a]"}>
                      {resolvedLeadId
                        ? (leads.find((l) => l.id === resolvedLeadId)?.name ??
                           leads.find((l) => l.id === resolvedLeadId)?.phone ??
                           "Lead selecionado")
                        : "Selecione o lead"}
                    </span>
                    <ChevronDownIcon className="size-4 text-[#8a8a8a]" />
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
                      <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Nenhum lead encontrado.</div>
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
                            setCreatingDeal(false);
                            setNewDealTitle("");
                            setNewDealPipeline("");
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

          {/* Itens do Bling — substituem produto em texto livre e valor único.
              Sem `blingEditable` (edição de venda sem pedido no ERP) nem vale
              esperar o status carregar: o resultado nunca muda essa venda para
              modo Bling, então mostrar o formulário legado direto evita um
              "verificando conexão" que não leva a lugar nenhum. */}
          {gate.mode === "loading" && blingEditable ? (
            <div className="px-5 py-8 text-center text-[13px] text-[#7b7b78]">
              Verificando conexão com o Bling…
            </div>
          ) : blingMode ? (
            <BlingOrderForm
              meta={{
                leadId: resolvedLeadId,
                dealId: lockedDealId ?? (dealId || null),
                soldAt,
                soldBy: soldBy && soldBy !== "__none__" ? soldBy : null,
                notes: notes.trim(),
              }}
              condicaoPagamento={blingCondicaoPagamento}
              initialLines={
                isEditing ? linesFromSaleItems(editingSale?.sale_items) : undefined
              }
              onChange={setOrderResult}
            />
          ) : (
            <>
              {/* Product */}
              <div>
                <label className={fieldLabel}>Produto / Serviço *</label>
                <Input
                  type="text"
                  value={product}
                  onChange={(e) => setProduct(e.target.value)}
                  placeholder="Ex: Café especial 5kg"
                  className={fieldInput}
                  required
                />
              </div>

              {/* Value */}
              <div>
                <label className={fieldLabel}>Valor (R$) *</label>
                <Input
                  type="number"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="0,00"
                  min="0"
                  step="0.01"
                  className={fieldInput}
                  required
                />
              </div>
            </>
          )}

          {/* Sale date */}
          <div>
            <label className={fieldLabel}>Data da Venda</label>
            <Input
              type="date"
              value={soldAt}
              onChange={(e) => setSoldAt(e.target.value)}
              className={fieldInput}
            />
          </div>

          {/* Sold by */}
          <div>
            <label className={fieldLabel}>Vendedor</label>
            <Select value={soldBy || undefined} onValueChange={setSoldBy}>
              <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                <SelectValue placeholder="Nenhum" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value="__none__">Nenhum</SelectItem>
                {users.map((u) => (
                  <SelectItem key={u.id} value={u.email}>
                    {u.name || u.email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Deal block — hidden in edit mode */}
          {!isEditing && (
            <div>
              <label className={fieldLabel}>Deal{!lockedDealId ? " *" : ""}</label>

              {/* Locked deal — read-only */}
              {lockedDealId ? (
                <div className="w-full bg-[#faf9f6] border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111]">
                  {lockedDealTitle ?? lockedDealId}
                </div>
              ) : (
                <>
                  {/* Existing deal selector (when not creating a new one) */}
                  {!creatingDeal && (
                    <>
                      <Select
                        value={dealId || undefined}
                        onValueChange={(v) => {
                          if (v === "__new__") {
                            setDealId("");
                            setCreatingDeal(true);
                          } else {
                            setDealId(v);
                          }
                        }}
                      >
                        <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                          <SelectValue placeholder="Selecione ou crie um deal" />
                        </SelectTrigger>
                        <SelectContent position="popper">
                          {deals.map((d) => (
                            <SelectItem key={d.id} value={d.id}>
                              {d.title}
                            </SelectItem>
                          ))}
                          <SelectItem value="__new__">
                            + Criar novo deal
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      {dealId && dealId !== "__new__" && (
                        <p className="text-[11px] text-[#7b7b78] mt-1">
                          O deal será movido para Fechado Ganho automaticamente.
                        </p>
                      )}
                    </>
                  )}

                  {/* Inline new deal form */}
                  {creatingDeal && (
                    <div className="space-y-3 mt-1 p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[4px]">
                      <div>
                        <label className={fieldLabel}>Título do Deal *</label>
                        <Input
                          type="text"
                          value={newDealTitle}
                          onChange={(e) => setNewDealTitle(e.target.value)}
                          placeholder="Ex: Proposta Café 5kg"
                          className={fieldInput}
                        />
                      </div>
                      <div>
                        <label className={fieldLabel}>Funil *</label>
                        <Select
                          value={newDealPipeline || undefined}
                          onValueChange={setNewDealPipeline}
                        >
                          <SelectTrigger className="w-full h-[37px] bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
                            <SelectValue placeholder="Selecione o funil" />
                          </SelectTrigger>
                          <SelectContent position="popper">
                            {pipelines.map((p) => (
                              <SelectItem key={p.id} value={p.id}>
                                {p.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setCreatingDeal(false);
                          setNewDealTitle("");
                          setNewDealPipeline("");
                        }}
                        className="text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors underline underline-offset-2"
                      >
                        Cancelar novo deal
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Notes */}
          <div>
            <label className={fieldLabel}>Observação</label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Observações opcionais"
              className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none focus:ring-0 resize-none min-h-0"
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-[12px] text-red-600">{error}</p>
          )}

          {/* Por que o botão está desabilitado */}
          {blingMode && !error && !orderResult?.valid && (
            <p className="text-[11px] text-[#7b7b78]">
              Escolha ao menos um produto com quantidade e a forma de pagamento
              para lançar o pedido.
            </p>
          )}

          {gate.message && (
            <p className="text-[12px] text-red-600">{gate.message}</p>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving || !gate.canSubmit || (blingMode && !orderResult?.valid)}
              className="flex-1 py-2 text-[13px] font-medium text-white rounded-[4px] transition-colors bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78]"
            >
              {saving
                ? "Salvando..."
                : isEditing
                  ? "Salvar"
                  : blingMode
                    ? "Lançar pedido no Bling"
                    : "Registrar Venda"}
            </button>
          </div>
        </form>

        {/* 409 — o vendedor decide qual é o cliente no Bling */}
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

        {/* 201/202 — o número do pedido é a informação que o vendedor procura */}
        {sucesso && (
          <div className="p-5 text-center space-y-3">
            <div className="mx-auto w-10 h-10 rounded-full bg-[#1f9d57]/10 flex items-center justify-center">
              <CheckIcon className="size-5 text-[#1f9d57]" />
            </div>
            <p className="text-[15px] text-[#111111]">{sucesso.titulo}</p>
            <p className="text-[12px] text-[#7b7b78]">{sucesso.detalhe}</p>
            <button
              type="button"
              onClick={fecharModal}
              className="w-full py-2 text-[13px] font-medium text-white rounded-[4px] bg-[#1f9d57] hover:bg-[#1b8a4c] transition-colors"
            >
              Concluir
            </button>
          </div>
        )}

        {/* 422 na edição — o Bling recusou a alteração (pedido já faturado,
            tipicamente); o vendedor decide se a mudança vale só no CRM. */}
        {pendingBlingUpdate && (
          <div className="p-5 space-y-3">
            <p className="text-[13px] text-[#111111]">
              O Bling recusou a alteração:
            </p>
            <p className="text-[12px] text-red-600">{pendingBlingUpdate.message}</p>
            <p className="text-[12px] text-[#7b7b78]">
              Você pode salvar essa alteração só no CRM. A venda ficará marcada
              como divergente do Bling até alguém revisar.
            </p>
            <div className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setPendingBlingUpdate(null)}
                className="flex-1 py-2 text-[13px] text-[#7b7b78] border border-[#dedbd6] rounded-[4px] hover:bg-[#faf9f6] transition-colors"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={confirmSaveLocalOnly}
                disabled={saving}
                className="flex-1 py-2 text-[13px] font-medium text-white rounded-[4px] transition-colors bg-[#1f9d57] hover:bg-[#1b8a4c] disabled:bg-[#7b7b78]"
              >
                {saving ? "Salvando..." : "Salvar só no CRM"}
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

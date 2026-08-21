"use client";

import Link from "next/link";
import { Pencil, Trash2 } from "lucide-react";
import type { Sale } from "@/lib/types";
import { blingOrderUrl, orderLabel, saleStatus, type StatusTone } from "@/lib/sale-display";

// Cores da paleta da tabela para cada tom devolvido por saleStatus().
const TONE_COLOR: Record<StatusTone, string> = {
  neutral: "#7b7b78",
  warning: "#ff5600",
  danger: "#c41c1c",
};

interface SalesTableProps {
  sales: Sale[];
  loading: boolean;
  count: number;
  page: number;
  onPageChange: (p: number) => void;
  onEdit?: (sale: Sale) => void;
  onDelete?: (saleId: string) => void;
}

const LIMIT = 25;

export function SalesTable({ sales, loading, count, page, onPageChange, onEdit, onDelete }: SalesTableProps) {
  const totalPages = Math.ceil(count / LIMIT);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-12 bg-[#dedbd6]/30 rounded-[6px] animate-pulse" />
        ))}
      </div>
    );
  }

  if (sales.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#7b7b78]">Nenhuma venda encontrada para o período selecionado.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-[#dedbd6]">
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Data</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Lead</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Produto</th>
              <th className="text-right py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Valor</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Pedido</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Situação</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Vendedor</th>
              <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Deal</th>
              <th className="text-right py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Ações</th>
            </tr>
          </thead>
          <tbody>
            {sales.map((sale) => {
              const pedidoUrl = blingOrderUrl(sale.bling_order_id);
              // O numero do pedido so chega no enriquecimento/webhook; enquanto
              // nao chega, o link existe e o rotulo ainda nao — dai o fallback.
              const pedido = orderLabel(sale) || (pedidoUrl ? "Ver no Bling" : "");
              const situacao = saleStatus(sale);
              return (
              <tr key={sale.id} className="border-b border-[#dedbd6]/50 hover:bg-[#faf9f6] transition-colors">
                <td className="py-3 px-3 text-[#7b7b78] whitespace-nowrap">
                  {new Date(sale.sold_at).toLocaleDateString("pt-BR")}
                </td>
                <td className="py-3 px-3">
                  {sale.leads ? (
                    <Link
                      href={`/conversas?lead_id=${sale.lead_id}`}
                      className="text-[#111111] hover:underline truncate block max-w-[140px]"
                    >
                      {sale.leads.name || sale.leads.phone}
                    </Link>
                  ) : (
                    <span className="text-[#7b7b78]">—</span>
                  )}
                </td>
                <td className="py-3 px-3 text-[#111111] max-w-[200px] truncate">{sale.product}</td>
                <td className="py-3 px-3 text-[#111111] text-right whitespace-nowrap font-medium">
                  R$ {Number(sale.value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}
                </td>
                <td className="py-3 px-3 whitespace-nowrap">
                  {!pedido ? (
                    <span className="text-[#7b7b78]">—</span>
                  ) : pedidoUrl ? (
                    <a
                      href={pedidoUrl}
                      target="_blank"
                      rel="noreferrer"
                      title="Abrir pedido no Bling"
                      className="text-[#111111] hover:underline"
                    >
                      {pedido}
                    </a>
                  ) : (
                    <span className="text-[#111111]">{pedido}</span>
                  )}
                </td>
                <td className="py-3 px-3 whitespace-nowrap">
                  <span className="text-[12px]" style={{ color: TONE_COLOR[situacao.tone] }}>
                    {situacao.label}
                  </span>
                  {sale.bling_divergent && (
                    <span
                      title={
                        sale.bling_divergence?.fields.length
                          ? `Divergente do Bling: ${sale.bling_divergence.fields.join(", ")}`
                          : "Divergente do Bling"
                      }
                      className="ml-1.5 text-[10px] font-semibold px-1.5 py-0.5 rounded-[4px] border"
                      style={{ color: TONE_COLOR.danger, borderColor: TONE_COLOR.danger }}
                    >
                      DIVERGENTE
                    </span>
                  )}
                </td>
                <td className="py-3 px-3 text-[#7b7b78] max-w-[140px] truncate">{sale.sold_by || "—"}</td>
                <td className="py-3 px-3">
                  {sale.deals ? (
                    <span className="text-[12px] text-[#7b7b78] truncate block max-w-[120px]">{sale.deals.title}</span>
                  ) : (
                    <span className="text-[#7b7b78]">—</span>
                  )}
                </td>
                <td className="py-3 px-3 text-right whitespace-nowrap">
                  <div className="inline-flex items-center gap-1">
                    <button
                      type="button"
                      title="Editar venda"
                      aria-label="Editar venda"
                      onClick={() => onEdit?.(sale)}
                      className="p-1 rounded text-[#7b7b78] hover:text-[#111111] hover:bg-[#f0ede8] transition-colors"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      type="button"
                      title="Excluir venda"
                      aria-label="Excluir venda"
                      onClick={() => onDelete?.(sale.id)}
                      className="p-1 rounded text-[#7b7b78] hover:text-red-600 hover:bg-red-50 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-4">
          <p className="text-[12px] text-[#7b7b78]">
            {count} vendas · página {page} de {totalPages}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
              className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Anterior
            </button>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Próxima
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

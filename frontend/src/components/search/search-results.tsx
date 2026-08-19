"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { isOutboundMatch } from "@/lib/message-search";
import type { SearchTab } from "@/lib/universal-search";
import type { UniversalSearchResults } from "@/hooks/use-universal-search";
import type {
  LeadSearchResult,
  DealSearchResult,
  SaleSearchResult,
  ConversationSearchResult,
} from "@/lib/types";

const rowClass =
  "flex items-center justify-between gap-4 px-3 py-3 border-b border-[#dedbd6]/50 hover:bg-[#faf9f6] transition-colors";
const primaryText = "text-[14px] text-[#111111] font-medium truncate";
const secondaryText = "text-[12px] text-[#7b7b78] truncate";
const metaText = "text-[12px] text-[#7b7b78] whitespace-nowrap flex-shrink-0";

function currency(value: number | null): string {
  return Number(value ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("pt-BR");
}

/** Junta as partes não vazias da linha secundária com o separador padrão. */
function joinParts(parts: Array<string | null | undefined>): string {
  const kept = parts.filter((p): p is string => !!p && p.trim() !== "");
  return kept.length > 0 ? kept.join(" · ") : "—";
}

function LeadRow({ lead }: { lead: LeadSearchResult }) {
  return (
    <Link href={`/leads?lead_id=${lead.id}`} className={rowClass}>
      <div className="min-w-0">
        <p className={primaryText}>{lead.name || lead.company || lead.nome_fantasia || lead.phone}</p>
        <p className={secondaryText}>{joinParts([lead.company || lead.nome_fantasia, lead.phone])}</p>
      </div>
      <span className={metaText}>{shortDate(lead.created_at)}</span>
    </Link>
  );
}

function DealRow({ deal }: { deal: DealSearchResult }) {
  const funnel = joinParts([deal.pipeline_name, deal.stage_label]);
  return (
    <Link href={`/vendas?deal_id=${deal.id}`} className={rowClass}>
      <div className="min-w-0">
        <p className={primaryText}>{deal.title}</p>
        <p className={secondaryText}>
          {joinParts([deal.lead_name || deal.lead_phone, funnel === "—" ? null : funnel])}
        </p>
      </div>
      <span className={metaText}>{currency(deal.value)}</span>
    </Link>
  );
}

function SaleRow({ sale }: { sale: SaleSearchResult }) {
  return (
    <Link href={`/painel-vendas?sale_id=${sale.id}`} className={rowClass}>
      <div className="min-w-0">
        <p className={primaryText}>{sale.product}</p>
        <p className={secondaryText}>
          {joinParts([sale.lead_name || sale.lead_phone, sale.deal_title, shortDate(sale.sold_at)])}
        </p>
      </div>
      <span className={metaText}>{currency(sale.value)}</span>
    </Link>
  );
}

function ConversationRow({ item }: { item: ConversationSearchResult }) {
  const outbound = isOutboundMatch(item.sent_by);
  return (
    <Link
      href={item.lead_id ? `/conversas?lead_id=${item.lead_id}` : "/conversas"}
      className={rowClass}
    >
      <div className="min-w-0">
        <p className={primaryText}>{item.lead_name || item.lead_phone || "Contato"}</p>
        <p className={secondaryText}>
          {outbound && <span className="text-[#4b7bbf] font-medium">Você: </span>}
          {item.snippet || "Mensagem sem texto"}
        </p>
      </div>
      <span className={metaText}>{item.channel_name || "—"}</span>
    </Link>
  );
}

function Section({
  title,
  count,
  shown,
  onSeeAll,
  children,
}: {
  title: string;
  count: number;
  shown: number;
  /** Só na aba "Tudo": leva para a aba cheia da entidade. `null` esconde o atalho. */
  onSeeAll: (() => void) | null;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center justify-between px-3 pt-4 pb-1.5">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">{title}</p>
        {onSeeAll && count > shown && (
          <button
            type="button"
            onClick={onSeeAll}
            className="inline-flex items-center gap-0.5 text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors"
          >
            ver todos ({count})
            <ChevronRight size={13} />
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

interface SearchResultsProps {
  tab: SearchTab;
  results: UniversalSearchResults;
  onTabChange: (tab: SearchTab) => void;
}

export function SearchResults({ tab, results, onTabChange }: SearchResultsProps) {
  const showAll = tab === "all";
  const showLeads = showAll || tab === "leads";
  const showDeals = showAll || tab === "deals";
  const showSales = showAll || tab === "sales";
  const showConversations = showAll || tab === "conversations";

  // Vazio é sempre relativo à aba ativa: 0 leads com deals achados ainda é
  // "nada encontrado" quando o usuário está na aba Leads.
  const isEmpty =
    (!showLeads || results.leads.data.length === 0) &&
    (!showDeals || results.deals.data.length === 0) &&
    (!showSales || results.sales.data.length === 0) &&
    (!showConversations || results.conversations.data.length === 0);

  if (isEmpty) {
    return (
      <div className="py-12 text-center">
        <p className="text-[14px] text-[#7b7b78]">Nenhum resultado encontrado.</p>
      </div>
    );
  }

  return (
    <div>
      {showLeads && results.leads.data.length > 0 && (
        <Section
          title="Leads"
          count={results.leads.count}
          shown={results.leads.data.length}
          onSeeAll={showAll ? () => onTabChange("leads") : null}
        >
          {results.leads.data.map((lead) => (
            <LeadRow key={lead.id} lead={lead} />
          ))}
        </Section>
      )}

      {showDeals && results.deals.data.length > 0 && (
        <Section
          title="Deals"
          count={results.deals.count}
          shown={results.deals.data.length}
          onSeeAll={showAll ? () => onTabChange("deals") : null}
        >
          {results.deals.data.map((deal) => (
            <DealRow key={deal.id} deal={deal} />
          ))}
        </Section>
      )}

      {showSales && results.sales.data.length > 0 && (
        <Section
          title="Vendas"
          count={results.sales.count}
          shown={results.sales.data.length}
          onSeeAll={showAll ? () => onTabChange("sales") : null}
        >
          {results.sales.data.map((sale) => (
            <SaleRow key={sale.id} sale={sale} />
          ))}
        </Section>
      )}

      {showConversations && results.conversations.data.length > 0 && (
        <Section
          title="Conversas"
          count={results.conversations.count}
          shown={results.conversations.data.length}
          onSeeAll={showAll ? () => onTabChange("conversations") : null}
        >
          {results.conversations.data.map((item) => (
            <ConversationRow key={item.message_id} item={item} />
          ))}
        </Section>
      )}
    </div>
  );
}

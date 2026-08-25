"use client";

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCurrentRole } from "@/hooks/use-current-role";
import type { TeamUser } from "@/lib/types";
import type { QuotesFilters } from "@/hooks/use-quotes";
import type { QuoteStatus } from "@/lib/quotes/quote-display";

interface QuotesFiltersBarProps {
  filters: QuotesFilters;
  onChange: (f: QuotesFilters) => void;
}

/**
 * Radix trata `value=""` como "sem selecao" e recusa um `SelectItem` com valor
 * vazio — entao "Todos" precisa de um valor real. O sentinela e traduzido para
 * `undefined` na saida para nunca chegar a query string: `?status=__todos`
 * viraria `.eq("status", "__todos")` na rota e devolveria lista vazia.
 */
const TODOS = "__todos";

const SITUACOES: { value: QuoteStatus; label: string }[] = [
  { value: "rascunho", label: "Rascunho" },
  { value: "enviado", label: "Enviado" },
  { value: "aprovado", label: "Aprovado" },
  { value: "nao_aprovado", label: "Não aprovado" },
  { value: "convertido", label: "Convertido" },
  { value: "cancelado", label: "Cancelado" },
];

function startOfMonth(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
}
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// Rotulo e campo com a mesma casca das outras barras de filtro do CRM: rotulo em
// caixa alta, 11px, tracking largo — o padrao de `SaansMono` do DESIGN.md.
const ROTULO = "text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1";
// Os primitivos shadcn vem com borda cinza-fria (`--border` em oklch neutro) e
// raio 8px. O DESIGN.md pede oat quente (#dedbd6) e 4px; sobrescrever no
// className e a convencao ja usada em `campaign-report-table.tsx`, e e melhor
// que trocar os tokens globais, que mexeria em toda tela que ja usa shadcn.
const CAMPO =
  "h-9 bg-white border-[#dedbd6] rounded-[4px] text-[13px] text-[#111111] focus-visible:border-[#111111] focus-visible:ring-0";

export function QuotesFiltersBar({ filters, onChange }: QuotesFiltersBarProps) {
  const { role } = useCurrentRole();
  const isAdmin = role === "admin";
  const [users, setUsers] = useState<TeamUser[]>([]);

  useEffect(() => {
    // Só o admin tem o seletor de vendedor, então só ele paga a chamada. Para o
    // vendedor a lista seria inútil de qualquer forma: o escopo já o prende ao
    // próprio e-mail, e ver os nomes dos colegas num filtro que não funciona
    // sugeriria um acesso que ele não tem.
    if (!isAdmin) return;
    fetch("/api/users")
      .then((r) => r.json())
      .then((data) => setUsers(Array.isArray(data) ? data : []))
      .catch(() => setUsers([]));
  }, [isAdmin]);

  // Toda mudança volta para a página 1: manter a página 7 ao trocar o período
  // deixaria a tabela vazia com uma paginação dizendo "página 7 de 2".
  const set = (patch: Partial<QuotesFilters>) => onChange({ ...filters, ...patch, page: 1 });

  return (
    <div className="flex flex-wrap gap-3 items-end">
      <div>
        <Label htmlFor="orcamento-de" className={ROTULO}>De</Label>
        <Input
          id="orcamento-de"
          type="date"
          value={filters.from ?? startOfMonth()}
          onChange={(e) => set({ from: e.target.value })}
          className={`${CAMPO} w-[150px]`}
        />
      </div>
      <div>
        <Label htmlFor="orcamento-ate" className={ROTULO}>Até</Label>
        <Input
          id="orcamento-ate"
          type="date"
          value={filters.to ?? today()}
          onChange={(e) => set({ to: e.target.value })}
          className={`${CAMPO} w-[150px]`}
        />
      </div>
      <div>
        <p className={ROTULO}>Situação</p>
        <Select
          value={filters.status ?? TODOS}
          onValueChange={(v) => set({ status: v === TODOS ? undefined : v })}
        >
          <SelectTrigger className={`${CAMPO} w-[160px]`} aria-label="Situação">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TODOS}>Todas</SelectItem>
            {SITUACOES.map((s) => (
              <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {isAdmin && (
        <div>
          <p className={ROTULO}>Vendedor</p>
          <Select
            value={filters.createdBy ?? TODOS}
            onValueChange={(v) => set({ createdBy: v === TODOS ? undefined : v })}
          >
            <SelectTrigger className={`${CAMPO} w-[190px]`} aria-label="Vendedor">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={TODOS}>Todos</SelectItem>
              {users.map((u) => (
                <SelectItem key={u.id} value={u.email}>{u.name || u.email}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="flex-1 min-w-[200px]">
        <Label htmlFor="orcamento-busca" className={ROTULO}>Buscar cliente</Label>
        <Input
          id="orcamento-busca"
          type="text"
          value={filters.search ?? ""}
          onChange={(e) => set({ search: e.target.value || undefined })}
          placeholder="Nome do cliente"
          className={`${CAMPO} w-full`}
        />
      </div>
    </div>
  );
}

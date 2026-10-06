"use client";

/**
 * Seletor de lead dos modais de venda e orçamento (modo `pickLead`).
 *
 * Antes carregava `/api/leads` inteiro e filtrava no browser — o PostgREST
 * corta em 1.000 linhas, então quem estava fora das 1.000 mais recentes não
 * existia para o seletor. Agora cada busca vai ao servidor
 * (`/api/conversations/search-contacts`, a mesma da lista de conversas), com
 * respiro entre as teclas.
 *
 * Limite conhecido: a busca é sobre conversas, dentro dos canais do usuário —
 * lead sem conversa não aparece. Para venda isso é o esperado (o vendedor
 * vende para quem conversou).
 */
import { useEffect, useState } from "react";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { CONTACT_SEARCH_MIN_LEN } from "@/lib/contact-search";
import type { DadosDeContato } from "./lead-cliente";

export interface LeadEscolhido extends DadosDeContato {
  id: string;
}

export const ATRASO_BUSCA_MS = 300;

/** Conversas de `search-contacts` → um lead por id, na ordem recebida. */
export function leadsDaBusca(linhas: unknown): LeadEscolhido[] {
  if (!Array.isArray(linhas)) return [];
  const vistos = new Set<string>();
  const out: LeadEscolhido[] = [];
  for (const linha of linhas) {
    const l = (linha as { leads?: LeadEscolhido | null } | null)?.leads;
    if (!l?.id || vistos.has(l.id)) continue;
    vistos.add(l.id);
    out.push({
      id: l.id,
      name: l.name ?? null,
      phone: l.phone ?? null,
      email: l.email ?? null,
      cnpj: l.cnpj ?? null,
      razao_social: l.razao_social ?? null,
    });
  }
  return out;
}

interface LeadPickerProps {
  selecionado: LeadEscolhido | null;
  onEscolher: (lead: LeadEscolhido) => void;
}

export function LeadPicker({ selecionado, onEscolher }: LeadPickerProps) {
  const [aberto, setAberto] = useState(false);
  const [termo, setTermo] = useState("");
  const [resultado, setResultado] = useState<{
    termo: string;
    leads: LeadEscolhido[];
    erro: boolean;
  } | null>(null);

  const q = termo.trim();
  const curto = q.length < CONTACT_SEARCH_MIN_LEN;

  useEffect(() => {
    if (curto) return;
    let vivo = true;
    const timer = setTimeout(() => {
      fetch(`/api/conversations/search-contacts?q=${encodeURIComponent(q)}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((d) => {
          if (vivo) setResultado({ termo: q, leads: leadsDaBusca(d), erro: false });
        })
        .catch(() => {
          if (vivo) setResultado({ termo: q, leads: [], erro: true });
        });
    }, ATRASO_BUSCA_MS);
    return () => {
      vivo = false;
      clearTimeout(timer);
    };
  }, [q, curto]);

  const atual = !curto && resultado?.termo === q ? resultado : null;
  const buscando = !curto && !atual;

  return (
    <Popover open={aberto} onOpenChange={setAberto}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="flex w-full h-[37px] items-center justify-between bg-white border border-[#dedbd6] rounded-[4px] px-3 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none"
        >
          <span className={selecionado ? "truncate" : "text-[#8a8a8a]"}>
            {selecionado
              ? (selecionado.name ?? selecionado.phone ?? "Lead selecionado")
              : "Selecione o lead"}
          </span>
          <ChevronDownIcon className="size-4 shrink-0 text-[#8a8a8a]" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="p-0" portal={false}>
        <div className="p-2 border-b border-[#eee]">
          <Input
            autoFocus
            value={termo}
            onChange={(e) => setTermo(e.target.value)}
            placeholder="Buscar por nome, telefone, e-mail ou CNPJ..."
            className="h-8 text-[14px]"
          />
        </div>
        <div className="max-h-64 overflow-y-auto p-1">
          {curto && (
            <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">
              Digite ao menos {CONTACT_SEARCH_MIN_LEN} letras para buscar.
            </div>
          )}
          {buscando && <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Buscando...</div>}
          {atual?.erro && (
            <div className="px-2 py-3 text-[13px] text-[#c41c1c]">
              Não foi possível buscar. Tente de novo.
            </div>
          )}
          {atual && !atual.erro && atual.leads.length === 0 && (
            <div className="px-2 py-3 text-[13px] text-[#8a8a8a]">Nenhum lead encontrado.</div>
          )}
          {atual?.leads.map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => {
                onEscolher(l);
                setAberto(false);
                setTermo("");
              }}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[14px] hover:bg-[#f4f2ee]"
            >
              <span className="min-w-0">
                <span className="block truncate">{l.name ?? l.phone}</span>
                {l.name && l.phone && (
                  <span className="block text-[11px] text-[#7b7b78] truncate">{l.phone}</span>
                )}
              </span>
              {selecionado?.id === l.id && <CheckIcon className="size-4 shrink-0" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

"use client";

import { useEffect, useState } from "react";

/**
 * Cadastro único de vendedores (cartão b67f1c6b). `assigned_to` de deal e de lead
 * guarda o id de `public.vendedores`; a tela escolhe numa lista em vez de texto livre.
 */
export interface Vendedor {
  id: string;
  nome: string;
  email: string;
  ativo: boolean;
}

// Uma busca por página: o kanban renderiza dezenas de cards e todos leem a mesma lista.
let cache: Promise<Vendedor[]> | null = null;

export function carregarVendedores(): Promise<Vendedor[]> {
  if (!cache) {
    cache = fetch("/api/vendedores")
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => (Array.isArray(d) ? (d as Vendedor[]) : []))
      .catch(() => [] as Vendedor[])
      .then((lista) => {
        if (!lista.length) cache = null; // falha/vazio: tenta de novo na próxima montagem
        return lista;
      });
  }
  return cache;
}

/** Só para testes. */
export function _limparCacheVendedores() {
  cache = null;
}

/** Todos os vendedores (ativos e inativos); null enquanto carrega. */
export function useVendedores(): Vendedor[] | null {
  const [lista, setLista] = useState<Vendedor[] | null>(null);
  useEffect(() => {
    let vivo = true;
    void carregarVendedores().then((l) => {
      if (vivo) setLista(l);
    });
    return () => {
      vivo = false;
    };
  }, []);
  return lista;
}

export function nomeDoVendedor(lista: Vendedor[] | null, id: string | null | undefined): string | null {
  if (!lista || !id) return null;
  return lista.find((v) => v.id === id)?.nome ?? null;
}

interface VendedorSelectProps {
  value: string | null | undefined;
  onChange: (id: string | null) => void;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

const CLASSE_PADRAO =
  "bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full";

export function VendedorSelect({ value, onChange, className, disabled, "aria-label": ariaLabel }: VendedorSelectProps) {
  const lista = useVendedores();
  const atual = value || "";
  const ativos = (lista ?? []).filter((v) => v.ativo);
  const atribuido = atual ? (lista ?? []).find((v) => v.id === atual) : undefined;
  // O valor gravado sempre aparece, mesmo de vendedor inativo ou ainda carregando:
  // senão o <select> mostraria "Sem vendedor" e um Salvar apagaria o dono.
  const extra =
    atual && !ativos.some((v) => v.id === atual)
      ? {
          id: atual,
          nome: atribuido ? `${atribuido.nome} (inativo)` : lista ? "Vendedor desconhecido" : "Carregando...",
        }
      : null;

  return (
    <select
      value={atual}
      onChange={(e) => onChange(e.target.value || null)}
      disabled={disabled}
      aria-label={ariaLabel ?? "Vendedor"}
      className={className ?? CLASSE_PADRAO}
    >
      <option value="">Sem vendedor</option>
      {extra && <option value={extra.id}>{extra.nome}</option>}
      {ativos.map((v) => (
        <option key={v.id} value={v.id}>
          {v.nome}
        </option>
      ))}
    </select>
  );
}

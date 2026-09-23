"use client";

/**
 * Modal "Preços da ValerIA" — edita `products.price_formatted` (o catálogo que
 * a ValerIA oferta), via /api/admin/valeria-catalog. Não tem relação com o
 * espelho do Bling listado na página. Todas as alterações vão num único PATCH;
 * se ele falhar, as edições ficam na tela para o admin tentar de novo.
 */

import { useEffect, useMemo, useState } from "react";
import { formatPrecoCatalogo, type CatalogItem } from "@/lib/valeria-catalog";
import { calcularAlteracoes, textoInicial } from "./valeria-precos-diff";

interface Props {
  onClose: () => void;
  onSaved: (quantidade: number) => void;
}

export function ValeriaPrecosModal({ onClose, onSaved }: Props) {
  const [itens, setItens] = useState<CatalogItem[]>([]);
  const [textos, setTextos] = useState<Record<string, string>>({});
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    fetch("/api/admin/valeria-catalog", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((body: { data: CatalogItem[] }) => {
        if (cancelado) return;
        setItens(body.data ?? []);
        setTextos(Object.fromEntries((body.data ?? []).map((i) => [i.id, textoInicial(i)])));
      })
      .catch(() => {
        if (!cancelado) setErro("Não foi possível carregar os preços da ValerIA.");
      })
      .finally(() => {
        if (!cancelado) setCarregando(false);
      });
    return () => {
      cancelado = true;
    };
  }, []);

  useEffect(() => {
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !salvando) onClose();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [onClose, salvando]);

  const { alteracoes, invalidos } = useMemo(() => calcularAlteracoes(itens, textos), [itens, textos]);
  const alterados = useMemo(() => new Set(alteracoes.map((a) => a.id)), [alteracoes]);
  const setores = useMemo(() => {
    const grupos = new Map<string, CatalogItem[]>();
    for (const item of itens) grupos.set(item.sector, [...(grupos.get(item.sector) ?? []), item]);
    return [...grupos.entries()];
  }, [itens]);

  const podeSalvar = alteracoes.length > 0 && invalidos.length === 0 && !salvando;

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      const res = await fetch("/api/admin/valeria-catalog", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ itens: alteracoes }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErro(body.error ?? "Não foi possível salvar os preços.");
        return;
      }
      onSaved(alteracoes.length);
      onClose();
    } catch {
      setErro("Não foi possível salvar os preços.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#111111]/30 p-3 sm:p-4"
      onClick={() => !salvando && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="valeria-precos-titulo"
        className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-[8px] border border-[#dedbd6] bg-white shadow-[0_12px_40px_-12px_rgba(17,17,17,0.25)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Cabeçalho */}
        <div className="flex items-start justify-between gap-3 border-b border-[#dedbd6] px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <h2 id="valeria-precos-titulo" className="text-[16px] font-semibold tracking-tight text-[#111111]">
              Preços da ValerIA
            </h2>
            <p className="mt-0.5 text-[12px] text-[#7b7b78]">
              Valores que a ValerIA oferece aos leads, por produto.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={salvando}
            aria-label="Fechar"
            className="-mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] text-[18px] leading-none text-[#7b7b78] transition-colors hover:bg-[#faf9f6] hover:text-[#111111] disabled:opacity-40"
          >
            ×
          </button>
        </div>

        {/* Lista */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden">
          {carregando ? (
            <div className="space-y-2 px-4 py-4 sm:px-5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-[6px] bg-[#dedbd6]/30" />
              ))}
            </div>
          ) : setores.length === 0 ? (
            !erro && (
              <p className="px-5 py-12 text-center text-[13px] text-[#7b7b78]">
                Nenhum item no catálogo da ValerIA.
              </p>
            )
          ) : (
            setores.map(([setor, doSetor]) => (
              <section key={setor}>
                <h3 className="sticky top-0 z-10 flex items-baseline justify-between border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-1.5 text-[11px] font-medium uppercase tracking-[0.6px] text-[#7b7b78] sm:px-5">
                  <span className="truncate">{setor}</span>
                  <span className="ml-3 shrink-0 tabular-nums normal-case tracking-normal">
                    {doSetor.length} {doSetor.length === 1 ? "item" : "itens"}
                  </span>
                </h3>
                <ul className="divide-y divide-[#dedbd6]/60">
                  {doSetor.map((item) => {
                    const invalido = invalidos.includes(item.id);
                    const alterado = alterados.has(item.id);
                    return (
                      <li
                        key={item.id}
                        className={`flex items-center gap-3 border-l-2 py-2 pl-[14px] pr-4 transition-colors sm:pl-[18px] sm:pr-5 ${
                          invalido
                            ? "border-l-red-500 bg-red-50/40"
                            : alterado
                              ? "border-l-[#111111] bg-[#faf9f6]"
                              : "border-l-transparent"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] text-[#111111]" title={item.name}>
                            {item.name}
                          </p>
                          {invalido ? (
                            <p className="text-[11px] text-red-600">Valor inválido</p>
                          ) : alterado ? (
                            <p className="text-[11px] tabular-nums text-[#7b7b78]">
                              era{" "}
                              <span className="line-through">
                                {item.preco === null ? "sem preço" : formatPrecoCatalogo(item.preco)}
                              </span>
                            </p>
                          ) : null}
                        </div>
                        <label
                          className={`flex w-[118px] shrink-0 items-center rounded-[4px] border bg-white transition-colors focus-within:border-[#111111] ${
                            invalido
                              ? "border-red-500 focus-within:border-red-500"
                              : alterado
                                ? "border-[#111111]"
                                : "border-[#dedbd6]"
                          }`}
                        >
                          <span className="select-none pl-2 text-[12px] text-[#7b7b78]">R$</span>
                          <input
                            type="text"
                            inputMode="decimal"
                            placeholder="—"
                            aria-label={`Preço de ${item.name}`}
                            aria-invalid={invalido}
                            value={textos[item.id] ?? ""}
                            onChange={(e) => setTextos((t) => ({ ...t, [item.id]: e.target.value }))}
                            className={`w-full min-w-0 bg-transparent px-2 py-1.5 text-right text-[13px] tabular-nums text-[#111111] placeholder:text-[#dedbd6] focus:outline-none ${
                              alterado ? "font-medium" : ""
                            }`}
                          />
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
        </div>

        {/* Erro fica fora da área rolável: visível mesmo com a lista longa */}
        {erro && (
          <div role="alert" className="border-t border-red-200 bg-red-50 px-4 py-2 text-[12px] text-red-700 sm:px-5">
            {erro}
          </div>
        )}

        {/* Rodapé */}
        <div className="flex flex-col gap-3 border-t border-[#dedbd6] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p className="text-[12px] text-[#7b7b78]">A ValerIA passa a usar os novos valores em até 1 minuto.</p>
          <div className="flex shrink-0 justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={salvando}
              className="rounded-[4px] border border-[#dedbd6] px-3 py-1.5 text-[12px] text-[#111111] transition-colors hover:bg-[#faf9f6] disabled:opacity-40"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={salvar}
              disabled={!podeSalvar}
              className="rounded-[4px] bg-[#111111] px-3 py-1.5 text-[12px] tabular-nums text-white transition-colors hover:bg-[#333333] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {salvando ? "Salvando…" : `Salvar (${alteracoes.length})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

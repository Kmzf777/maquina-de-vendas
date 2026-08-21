"use client";

/**
 * Catalogo de produtos do Bling — leitura do ESPELHO local (`bling_products`
 * via GET /api/bling/catalog), nunca da API do Bling. Somente leitura: a
 * fonte de verdade e o Bling, o sync mantem o espelho atualizado.
 */

import { useEffect, useMemo, useState } from "react";
import { debounce } from "@/lib/debounce";

interface CatalogProduct {
  id: number;
  codigo: string | null;
  nome: string;
  preco: number | null;
  unidade: string | null;
  situacao: string | null;
  saldo_virtual: number | null;
  imagem_url: string | null;
}

const LIMIT = 50;

function formatMoney(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function situacaoLabel(s: string | null): string {
  if (s === "A") return "Ativo";
  if (s === "I") return "Inativo";
  return s || "—";
}

export default function ProdutosPage() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [situacao, setSituacao] = useState<"" | "A" | "I">("A");
  const [page, setPage] = useState(1);

  const [data, setData] = useState<CatalogProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Debounce só no termo de busca — trocar a situação ou a página aplica na hora.
  const buscar = useMemo(() => debounce((termo: string) => setDebouncedQuery(termo), 300), []);
  useEffect(() => {
    buscar(query);
    return () => buscar.cancel();
  }, [query, buscar]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPage(1);
  }, [debouncedQuery, situacao]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (debouncedQuery) params.set("q", debouncedQuery);
    if (situacao) params.set("situacao", situacao);
    params.set("page", String(page));
    params.set("limit", String(LIMIT));

    let cancelled = false;
    fetch(`/api/bling/catalog?${params}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((body) => {
        if (cancelled) return;
        setData(body.data ?? []);
        setTotal(body.total ?? 0);
      })
      .catch(() => {
        if (!cancelled) setError("Não foi possível carregar o catálogo.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, situacao, page]);

  const totalPages = Math.ceil(total / LIMIT);

  return (
    <div className="flex-1 overflow-y-auto bg-[#faf9f6]">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div>
          <h1 className="text-[22px] font-semibold text-[#111111] tracking-tight">Produtos</h1>
          <p className="text-[13px] text-[#7b7b78] mt-0.5">Catálogo sincronizado do Bling</p>
        </div>

        <div className="bg-white border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
                Buscar
              </label>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Nome ou código…"
                className="w-full bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] block mb-1">
                Situação
              </label>
              <select
                value={situacao}
                onChange={(e) => setSituacao(e.target.value as "" | "A" | "I")}
                className="bg-white border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[13px] text-[#111111] focus:border-[#111111] focus:outline-none"
              >
                <option value="A">Ativo</option>
                <option value="I">Inativo</option>
                <option value="">Todos</option>
              </select>
            </div>
          </div>

          {error && <p className="text-[13px] text-red-600">{error}</p>}

          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 bg-[#dedbd6]/30 rounded-[6px] animate-pulse" />
              ))}
            </div>
          ) : data.length === 0 ? (
            <div className="py-12 text-center">
              <p className="text-[14px] text-[#7b7b78]">Nenhum produto encontrado.</p>
            </div>
          ) : (
            <div>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b border-[#dedbd6]">
                      <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Código</th>
                      <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Nome</th>
                      <th className="text-right py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Preço</th>
                      <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Unidade</th>
                      <th className="text-right py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Saldo</th>
                      <th className="text-left py-3 px-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] font-medium">Situação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((p) => (
                      <tr key={p.id} className="border-b border-[#dedbd6]/50 hover:bg-[#faf9f6] transition-colors">
                        <td className="py-3 px-3 text-[#7b7b78] whitespace-nowrap">{p.codigo || "—"}</td>
                        <td className="py-3 px-3 text-[#111111] max-w-[320px] truncate">{p.nome}</td>
                        <td className="py-3 px-3 text-[#111111] text-right whitespace-nowrap font-medium">
                          {formatMoney(p.preco)}
                        </td>
                        <td className="py-3 px-3 text-[#7b7b78] whitespace-nowrap">{p.unidade || "—"}</td>
                        <td className="py-3 px-3 text-[#111111] text-right whitespace-nowrap">
                          {p.saldo_virtual ?? "—"}
                        </td>
                        <td className="py-3 px-3 whitespace-nowrap">
                          <span className="text-[12px]" style={{ color: p.situacao === "A" ? "#1f9d57" : "#7b7b78" }}>
                            {situacaoLabel(p.situacao)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {totalPages > 1 && (
                <div className="flex items-center justify-between pt-4">
                  <p className="text-[12px] text-[#7b7b78]">
                    {total} produtos · página {page} de {totalPages}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setPage((p) => p - 1)}
                      disabled={page === 1}
                      className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      Anterior
                    </button>
                    <button
                      onClick={() => setPage((p) => p + 1)}
                      disabled={page >= totalPages}
                      className="px-3 py-1.5 text-[12px] border border-[#dedbd6] rounded-[4px] text-[#111111] hover:bg-[#faf9f6] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      Próxima
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

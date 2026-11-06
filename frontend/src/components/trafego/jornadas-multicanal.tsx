"use client";

// Bloco "Jornadas com mais de um canal" do /trafego (F5, cartão B item 4): quantos leads e vendas
// do período passaram por 2 canais ou mais, e os caminhos mais comuns.
import type { JornadasResumo } from "@/lib/traffic-jornada";

const fmtBRL = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });

export function JornadasMulticanal({ jornadas }: { jornadas?: JornadasResumo | null }) {
  if (!jornadas) return null;
  const { leads, pedidos, receita, total_leads, caminhos } = jornadas;
  return (
    <section className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5" aria-label="Jornadas com mais de um canal">
      <div className="flex flex-col gap-1 md:flex-row md:items-baseline md:justify-between">
        <h2 className="text-[15px] font-medium text-[#111111]">Jornadas com mais de um canal</h2>
        <p className="text-[13px] text-[#7b7b78]">
          {leads} de {total_leads} lead{total_leads === 1 ? "" : "s"} · {pedidos} venda{pedidos === 1 ? "" : "s"}
          {receita > 0 ? ` · ${fmtBRL(receita)}` : ""}
        </p>
      </div>
      {caminhos.length === 0 ? (
        <p className="mt-3 text-[13px] text-[#7b7b78]">Nenhum lead do período passou por mais de um canal.</p>
      ) : (
        <ol className="mt-3 flex flex-col divide-y divide-[#f0ede8]">
          {caminhos.map((c) => (
            <li key={c.caminho} className="py-2 flex flex-col gap-0.5 md:flex-row md:items-center md:justify-between">
              <span className="text-[14px] text-[#111111]">{c.caminho}</span>
              <span className="text-[13px] text-[#7b7b78] tabular-nums">
                {c.leads} lead{c.leads === 1 ? "" : "s"} · {c.pedidos} venda{c.pedidos === 1 ? "" : "s"}
                {c.receita > 0 ? ` · ${fmtBRL(c.receita)}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

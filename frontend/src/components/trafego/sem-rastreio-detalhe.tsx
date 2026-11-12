"use client";

// O que sobrou em "Sem rastreio" e por quê (F5, cartão C item 4). O botão abre a lista de leads
// (a mesma página de detalhe das campanhas, com a coluna "Motivo").
import type { SemRastreioResumo } from "@/lib/traffic-jornada";

export function SemRastreioDetalhe({ resumo, onAbrir }: { resumo?: SemRastreioResumo | null; onAbrir?: () => void }) {
  if (!resumo || resumo.leads === 0) return null;
  return (
    <section className="bg-white border border-[#dedbd6] rounded-[8px] p-4 md:p-5" aria-label="Sem rastreio">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-medium text-[#111111]">
          Sem rastreio: {resumo.leads} lead{resumo.leads === 1 ? "" : "s"}
          {typeof resumo.clientes === "number" && resumo.clientes > 0
            ? ` · ${resumo.clientes} ${resumo.clientes === 1 ? "comprou" : "compraram"}` : ""}
        </h2>
        {onAbrir && (
          <button type="button" onClick={onAbrir}
            className="text-[13px] text-[#111111] underline underline-offset-2 whitespace-nowrap">
            Ver leads
          </button>
        )}
      </div>
      <ul className="mt-2 flex flex-col gap-1">
        {resumo.motivos.map((m) => (
          <li key={m.motivo} className="flex justify-between gap-3 text-[13px] text-[#7b7b78]">
            <span>{m.motivo}</span>
            <span className="tabular-nums">{m.leads}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

"use client";

// Seletor "Atribuir por: Última origem | Primeira origem" do /trafego (F5, cartão B).
import { ATRIBUICOES, type Atribuicao } from "@/lib/traffic-jornada";

export function AtribuicaoSelect({ value, onChange }: { value: Atribuicao; onChange: (a: Atribuicao) => void }) {
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Atribuir por">
      <span className="text-[13px] text-[#7b7b78] whitespace-nowrap">Atribuir por</span>
      <div className="inline-flex rounded-[4px] border border-[#111111] overflow-hidden">
        {ATRIBUICOES.map((a) => (
          <button
            key={a.value}
            type="button"
            title={a.ajuda}
            aria-pressed={value === a.value}
            onClick={() => onChange(a.value)}
            className={`px-2.5 py-1.5 text-[13px] whitespace-nowrap ${
              value === a.value ? "bg-[#111111] text-white" : "bg-transparent text-[#111111]"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

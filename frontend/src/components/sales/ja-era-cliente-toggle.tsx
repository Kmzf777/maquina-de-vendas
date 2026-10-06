"use client";

import type { FonteJaEraCliente } from "./lead-cliente";

interface JaEraClienteToggleProps {
  /** `null`/`undefined` = sem resposta: nenhum botão marcado. */
  valor: boolean | null | undefined;
  fonte?: FonteJaEraCliente | null;
  onEscolher: (valor: boolean) => void;
  desabilitado?: boolean;
  obrigatorio?: boolean;
  rotulo?: string;
}

/**
 * Sim/Não do "Já é cliente?". Dois botões sempre visíveis (não um select): a
 * pergunta é binária e o vendedor responde com um clique, no estilo do RD.
 * Selo "auto" quando quem marcou foi a regra do banco (venda anterior à
 * entrada do lead) — o vendedor vê de onde veio e pode sobrescrever.
 */
export function JaEraClienteToggle({
  valor,
  fonte,
  onEscolher,
  desabilitado,
  obrigatorio,
  rotulo = "Já é cliente?",
}: JaEraClienteToggleProps) {
  return (
    <div role="group" aria-label={rotulo} className="flex items-center gap-2 flex-wrap">
      <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
        {rotulo}
        {obrigatorio ? " *" : ""}
      </span>
      <div className="flex">
        {[true, false].map((opcao) => (
          <button
            key={String(opcao)}
            type="button"
            aria-pressed={valor === opcao}
            disabled={desabilitado}
            onClick={() => onEscolher(opcao)}
            className={`h-[26px] px-3 -ml-px first:ml-0 first:rounded-l-[4px] last:rounded-r-[4px] text-[12px] border transition-colors disabled:opacity-60 ${
              valor === opcao
                ? "bg-[#111111] border-[#111111] text-white"
                : "bg-white border-[#dedbd6] text-[#7b7b78] hover:text-[#111111]"
            }`}
          >
            {opcao ? "Sim" : "Não"}
          </button>
        ))}
      </div>
      {fonte === "auto" && (
        <span
          title="Marcado pelo sistema: há venda anterior à entrada do lead"
          className="px-1.5 py-0.5 rounded-[4px] text-[10px] uppercase tracking-[0.4px] bg-[#dedbd6]/60 text-[#7b7b78]"
        >
          auto
        </span>
      )}
    </div>
  );
}

import { formatTimeOnly } from "@/lib/datetime";

interface HandoffDividerProps {
  /** Momento do transbordo (created_at da mensagem-âncora). */
  at: string;
}

/**
 * Divisor visual full-width que marca o ponto de transbordo da Valéria (IA) para
 * o vendedor humano. Acima dele = histórico da IA; abaixo = conversa do vendedor.
 * Resolve a confusão do vendedor em distinguir as duas fases na thread única
 * (auditoria 2026-06-22, Problema 3).
 */
export function HandoffDivider({ at }: HandoffDividerProps) {
  return (
    <div className="flex items-center gap-2 my-4 px-2" data-testid="handoff-divider">
      <div className="flex-1 h-px bg-[#d4a840]/50" />
      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[12px] font-semibold whitespace-nowrap bg-[#fffbeb] text-[#7b5a00] border border-[#d4a840]/40">
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ flexShrink: 0 }}
        >
          <path d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15M12 9l3 3m0 0-3 3m3-3H3" />
        </svg>
        <span>Transbordo realizado</span>
        <span style={{ opacity: 0.5 }}>·</span>
        <span style={{ opacity: 0.75 }}>{formatTimeOnly(at)}</span>
      </div>
      <div className="flex-1 h-px bg-[#d4a840]/50" />
    </div>
  );
}

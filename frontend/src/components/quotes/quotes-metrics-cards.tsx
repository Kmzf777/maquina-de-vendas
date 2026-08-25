"use client";

import { formatarBRL, formatarTaxa } from "@/lib/quotes/quote-display";

export interface QuotesMetrics {
  count: number;
  total_value: number;
  avg_value: number;
  /** 0..1, ou `null` quando nada foi decidido no periodo. */
  approval_rate: number | null;
  approved_count: number;
  decided_count: number;
}

interface QuotesMetricsCardsProps {
  metrics: QuotesMetrics | null;
  loading: boolean;
}

function MetricCard({
  label,
  value,
  loading,
  children,
}: {
  label: string;
  value: string;
  loading: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4">
      <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">{label}</p>
      {loading ? (
        <div className="h-7 w-24 bg-[#dedbd6]/40 rounded-[4px] animate-pulse" />
      ) : (
        <>
          <p className="text-[22px] font-semibold text-[#111111] leading-none">{value}</p>
          {children}
        </>
      )}
    </div>
  );
}

/**
 * Barra de proporcao sob a taxa de aprovacao.
 *
 * A taxa e o unico dos quatro numeros que e uma RAZAO, e uma porcentagem sozinha
 * esconde de quantos orcamentos ela saiu: "100%" de um unico orcamento aprovado
 * le igual a "100%" de quarenta. A barra mais o "3 de 5" devolvem o denominador
 * sem gastar um quinto card.
 *
 * Some inteira quando nao ha denominador: desenhar um trilho vazio ao lado do
 * travessao sugeriria zero por cento, que e justamente o que o travessao existe
 * para nao dizer.
 */
function ApprovalMeter({ approved, decided }: { approved: number; decided: number }) {
  if (decided <= 0) {
    return (
      <p className="text-[11px] text-[#7b7b78] mt-2.5 leading-none">
        Nenhum orçamento decidido
      </p>
    );
  }
  const pct = Math.min(100, Math.max(0, (approved / decided) * 100));
  return (
    <div className="mt-2.5">
      <div className="h-[3px] w-full bg-[#dedbd6] rounded-full overflow-hidden">
        <div
          className="h-full bg-[#111111] rounded-full transition-[width] duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[11px] text-[#7b7b78] mt-1.5 leading-none">
        {approved} de {decided} decididos
      </p>
    </div>
  );
}

/**
 * Os quatro indicadores de /orcamento.
 *
 * Os QUATRO respondem a todos os filtros da barra, inclusive vendedor — nao ha
 * aqui o caso do "ciclo médio de recompra" de /painel-vendas, que responde ao
 * vendedor mas nao ao periodo. A rota `/api/quotes/metrics` calcula os quatro na
 * mesma consulta, entao nao existe caminho por onde um deles escape do recorte
 * (era o defeito corrigido em 85598b89).
 *
 * `metrics` nulo e o estado de ERRO, nao o de carregando (esse e `loading`), e e
 * por isso que os valores caem em zero em vez de repetirem o esqueleto: uma tela
 * presa no esqueleto para sempre nao diz que algo falhou.
 */
export function QuotesMetricsCards({ metrics, loading }: QuotesMetricsCardsProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        label="Orçamentos no período"
        value={metrics ? String(metrics.count) : "0"}
        loading={loading}
      />
      <MetricCard
        label="Valor total proposto"
        value={formatarBRL(metrics?.total_value ?? 0)}
        loading={loading}
      />
      <MetricCard
        label="Taxa de aprovação"
        // `formatarTaxa(null)` devolve travessao. Sem isso, um periodo so com
        // rascunhos mostraria "NaN%" (0/0 em JS) ou, pior, um "0%" convincente
        // que afirma reprovacao onde nao houve decisao nenhuma.
        value={formatarTaxa(metrics?.approval_rate ?? null)}
        loading={loading}
      >
        <ApprovalMeter
          approved={metrics?.approved_count ?? 0}
          decided={metrics?.decided_count ?? 0}
        />
      </MetricCard>
      <MetricCard
        label="Ticket médio"
        value={formatarBRL(metrics?.avg_value ?? 0)}
        loading={loading}
      />
    </div>
  );
}
